"""配置中心服务 —— 版本化的运行时配置管理

它在原有「白名单 + setattr」的基础上补三样东西：

1. **版本号与观察者**
   每次变更递增版本号，并通知订阅者。因为「把值写进 settings 对象」只完成了
   一半工作：消费方如果在启动时就把值拷进了自己的属性（缓存），改了 settings
   它也不会知道。版本号给了消费方一个「我手里的值过期了」的判断依据。

2. **校验（类型 / 范围 / 枚举 / 只读）**
   原实现只有类型转换，int 字段可以塞 -999、相似度阈值可以塞 5.0。
   这类值不会报错，只会让检索静默失效。

3. **审计**
   每次变更落库，记录谁、何时、把哪个字段从什么改成了什么（敏感字段脱敏）。

线程安全：全部写路径走同一把可重入锁，读路径读快照，避免并发读写脏读。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Union

from src.config import Settings, settings
from src.config_center import audit as audit_store
from src.config_center.categories import CONFIG_CATEGORIES
from src.config_center.schema import (
    get_spec,
    is_readonly,
    is_sensitive,
    readonly_reason,
)

logger = logging.getLogger(__name__)

# 敏感字段判定统一由 schema.is_sensitive 提供（按 _ 切词的整词匹配），
# 这里不再重复定义关键词表，避免三处实现漂移。

# 所有可更新字段的白名单（由分类清单派生）
UPDATABLE_FIELDS: set = set()
for _cat in CONFIG_CATEGORIES.values():
    UPDATABLE_FIELDS.update(_cat["fields"])


# ---------------------------------------------------------------------------
# 异常：由接口层翻译成 HTTP 状态码
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """配置中心异常基类"""

    status_code = 400


class ConfigValidationError(ConfigError):
    """类型 / 范围 / 枚举校验失败 → 400"""


class ConfigReadOnlyError(ConfigError):
    """只读字段，改动需要重启 → 400"""


class ConfigNotFoundError(ConfigError):
    """字段不存在或不在白名单 → 404"""

    status_code = 404


# ---------------------------------------------------------------------------
# 字段类型工具
# ---------------------------------------------------------------------------


def get_field_type(field_name: str) -> type:
    """取字段的 Python 类型（剥离 Optional / Union）"""
    info = Settings.model_fields.get(field_name)
    if info is None:
        return str
    ann = info.annotation
    origin = getattr(ann, "__origin__", None)
    if origin is Union:
        args = [a for a in ann.__args__ if a is not type(None)]
        if args:
            return args[0]
    return ann or str


def get_field_default(field_name: str) -> Any:
    """取字段默认值"""
    info = Settings.model_fields.get(field_name)
    if info is None:
        return None
    if info.default is not None:
        return info.default
    if info.default_factory is not None:
        try:
            return info.default_factory()
        except Exception:
            return None
    return None


def coerce(field_name: str, raw: Any) -> Any:
    """按字段类型强制转换，失败抛 ConfigValidationError"""
    target = get_field_type(field_name)
    try:
        if target is bool:
            # 严格类型校验：只接受真正的 JSON 布尔值。
            #
            # 原实现会把 "yes" / "on" / "1" 这类字符串宽松地当作真值接受，
            # 后果是把客户端的笔误（例如把布尔写成字符串）静默变成一次成功写入，
            # 调用方以为改对了、实际语义未必是预期。配置是长期生效的东西，
            # 宁可让调用方当场收到 400，也不要替它猜。
            if isinstance(raw, bool):
                return raw
            raise ConfigValidationError(
                f"字段 {field_name} 期望布尔值 true 或 false，"
                f"不接受 {type(raw).__name__} 类型的 {raw!r}"
            )
        if target is int:
            # 显式拒绝 bool，因为 Python 里 True 会被 int() 静默转成 1
            if isinstance(raw, bool):
                raise ValueError("布尔值不能赋给整型字段")
            f = float(raw)
            if f != int(f):
                raise ValueError(f"{raw!r} 不是整数")
            return int(f)
        if target is float:
            if isinstance(raw, bool):
                raise ValueError("布尔值不能赋给浮点字段")
            return float(raw)
        if target is str:
            # dict / list 允许（kb_weights、doc_weights 这类 JSON 字符串配置）
            if isinstance(raw, dict | list):
                import json

                return json.dumps(raw, ensure_ascii=False)
            return str(raw)
        return raw
    except ConfigValidationError:
        raise
    except (ValueError, TypeError) as e:
        raise ConfigValidationError(
            f"字段 {field_name} 期望 {target.__name__} 类型，收到 {raw!r}：{e}"
        ) from e


def validate(field_name: str, value: Any) -> None:
    """范围与枚举校验（转换后调用）"""
    spec = get_spec(field_name)

    if spec.enum is not None:
        if value not in spec.enum:
            raise ConfigValidationError(
                f"字段 {field_name} 只接受 {list(spec.enum)} 之一，收到 {value!r}"
            )
        return

    if spec.min_value is not None or spec.max_value is not None:
        # 数值型才做范围判断；字符串字段若配了范围说明是配置错误，直接跳过
        if not isinstance(value, int | float) or isinstance(value, bool):
            return
        if spec.min_value is not None and value < spec.min_value:
            raise ConfigValidationError(
                f"字段 {field_name} 不能小于 {spec.min_value}{spec.unit}，收到 {value}"
            )
        if spec.max_value is not None and value > spec.max_value:
            raise ConfigValidationError(
                f"字段 {field_name} 不能大于 {spec.max_value}{spec.unit}，收到 {value}"
            )


# ---------------------------------------------------------------------------
# 配置中心
# ---------------------------------------------------------------------------


class ConfigCenter:
    """版本化配置中心（进程内单例）"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._version: int = 0
        self._observers: list[Callable[[int, dict[str, Any]], None]] = []
        # field -> {"at": iso 时间, "by": 操作人}
        self._modified: dict[str, dict[str, str]] = {}
        # 自检用：读取耗时统计
        self._read_ops: int = 0
        self._last_read_ms: float = 0.0
        self._last_change_at: str | None = None

    # ---- 版本与订阅 ----

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def subscribe(self, callback: Callable[[int, dict[str, Any]], None]) -> None:
        """订阅配置变更。callback(version, changes) 会在变更后同步调用。

        订阅者应当把回调实现得尽量轻（例如只置一个「需重载」标记），
        真正的重载动作留到下次使用时做，避免变更请求被消费方的初始化拖住。
        """
        with self._lock:
            self._observers.append(callback)

    def _notify_locked(self, changes: dict[str, Any]) -> None:
        """通知所有订阅者（调用方必须已持有锁）

        订阅者抛异常不影响变更本身，逐个隔离。
        """
        for cb in list(self._observers):
            try:
                cb(self._version, changes)
            except Exception as e:  # noqa: BLE001, PERF203 - 订阅者逐个隔离
                logger.warning("配置变更订阅者执行失败: %s", e)

    # ---- 读取 ----

    def get_value(self, field_name: str) -> Any:
        return getattr(settings, field_name, None)

    def mask(self, field_name: str, value: Any) -> Any:
        """敏感字段一律不返回明文，只回是否已设置"""
        if is_sensitive(field_name):
            return None
        return value

    def describe(self, field_name: str) -> dict[str, Any]:
        """单个字段的完整描述（供 API 返回）"""
        t0 = time.perf_counter()
        raw = self.get_value(field_name)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        with self._lock:
            self._read_ops += 1
            self._last_read_ms = elapsed_ms
            meta = dict(self._modified.get(field_name, {}))

        spec = get_spec(field_name)
        readonly = is_readonly(field_name)
        sensitive = is_sensitive(field_name)

        out: dict[str, Any] = {
            "key": field_name,
            "type": get_field_type(field_name).__name__,
            "default": get_field_default(field_name) if not sensitive else None,
            "is_sensitive": sensitive,
            "readonly": readonly,
            "hot": (not readonly) and (field_name in UPDATABLE_FIELDS),
            "modified_at": meta.get("at"),
            "modified_by": meta.get("by"),
        }
        if readonly:
            out["readonly_reason"] = readonly_reason(field_name)
            out["restart_required"] = True

        constraints = spec.describe()
        if constraints:
            out["constraints"] = constraints

        if sensitive:
            out["value"] = ""
            out["configured"] = bool(raw)
        else:
            out["value"] = raw
            out["is_default"] = raw == get_field_default(field_name)

        return out

    def list_fields(self, category: str | None = None) -> dict[str, Any]:
        """列出配置项（可按分类过滤）"""
        if category is not None and category not in CONFIG_CATEGORIES:
            available = list(CONFIG_CATEGORIES.keys())
            raise ConfigNotFoundError(
                f"配置分类不存在: {category}，可用分类: {available}"
            )

        items: list[dict[str, Any]] = []
        cats = [category] if category else list(CONFIG_CATEGORIES.keys())
        for cat_key in cats:
            for field_name in CONFIG_CATEGORIES[cat_key]["fields"]:
                desc = self.describe(field_name)
                desc["category"] = cat_key
                items.append(desc)

        return {
            "total": len(items),
            "field_count": len(UPDATABLE_FIELDS),
            "config_version": self.version,
            "items": items,
        }

    # ---- 写入 ----

    def _check_field(self, field_name: str) -> None:
        """写入前的字段合法性检查（只读 / 白名单）"""
        if is_readonly(field_name):
            raise ConfigReadOnlyError(
                f"字段 {field_name} 是启动时只读配置（{readonly_reason(field_name)}），"
                f"修改需要重启服务。请修改 .env 后重启容器。"
            )
        if field_name not in UPDATABLE_FIELDS:
            raise ConfigNotFoundError(
                f"配置项不存在或不可更新: {field_name}。可用字段见 GET /api/v1/config"
            )

    def set_value(
        self,
        field_name: str,
        raw_value: Any,
        operator: str = "",
        operator_ip: str = "",
        action: str = "update",
        source: str = "api",
    ) -> dict[str, Any]:
        """更新单个配置项并返回变更详情"""
        self._check_field(field_name)

        if is_sensitive(field_name):
            raise ConfigValidationError(
                f"字段 {field_name} 属敏感配置，不提供在线修改接口，"
                f"请通过环境变量或密钥管理下发"
            )

        with self._lock:
            old_value = self.get_value(field_name)
            new_value = coerce(field_name, raw_value)  # 抛 ConfigValidationError
            validate(field_name, new_value)  # 抛 ConfigValidationError

            changed = old_value != new_value
            if changed:
                setattr(settings, field_name, new_value)
                now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
                self._modified[field_name] = {"at": now, "by": operator or "unknown"}
                self._version += 1
                self._last_change_at = now

        # 审计与通知放在锁外：订阅者可能做重活，不能占着配置锁
        if changed:
            audit_store.record_change(
                config_key=field_name,
                old_value=old_value,
                new_value=new_value,
                operator=operator,
                operator_ip=operator_ip,
                action=action,
                hot_applied=True,
                source=source,
            )
            with self._lock:
                self._notify_locked({field_name: new_value})

        return {
            "key": field_name,
            "old_value": old_value,
            "new_value": new_value,
            "changed": changed,
            "config_version": self.version,
        }

    def set_batch(
        self,
        updates: dict[str, Any],
        operator: str = "",
        operator_ip: str = "",
        source: str = "api",
    ) -> dict[str, Any]:
        """批量更新。

        策略：先整体校验，再整体应用。
        校验阶段任何一项失败就返回 400 且不做任何修改，避免「改了一半」的中间态
        让人以为配置已生效。这与原实现的「逐项跳过」不同，后者会静默吞掉错误。
        """
        if not updates:
            raise ConfigValidationError("更新内容不能为空")

        prepared: dict[str, tuple[Any, Any]] = {}
        errors: list[dict[str, str]] = []

        for field_name, raw_value in updates.items():
            try:
                self._check_field(field_name)
                if is_sensitive(field_name):
                    raise ConfigValidationError(
                        f"字段 {field_name} 属敏感配置，不提供在线修改接口"
                    )
                with self._lock:
                    old_value = self.get_value(field_name)
                new_value = coerce(field_name, raw_value)
                validate(field_name, new_value)
                prepared[field_name] = (old_value, new_value)
            except ConfigError as e:  # noqa: PERF203 - 逐字段收集校验错误
                errors.append({"field": field_name, "reason": str(e)})

        if errors:
            raise ConfigValidationError(
                "批量更新被拒绝，未做任何修改："
                + "；".join(f"{e['field']} ({e['reason']})" for e in errors)
            )

        applied: list[dict[str, Any]] = []
        with self._lock:
            for field_name, (old_value, new_value) in prepared.items():
                if old_value == new_value:
                    continue
                setattr(settings, field_name, new_value)
                now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
                self._modified[field_name] = {"at": now, "by": operator or "unknown"}
                self._version += 1
                self._last_change_at = now
                applied.append(
                    {
                        "field": field_name,
                        "old_value": old_value,
                        "new_value": new_value,
                    }
                )

        for item in applied:
            audit_store.record_change(
                config_key=item["field"],
                old_value=item["old_value"],
                new_value=item["new_value"],
                operator=operator,
                operator_ip=operator_ip,
                action="batch_update",
                hot_applied=True,
                source=source,
            )

        if applied:
            with self._lock:
                self._notify_locked({i["field"]: i["new_value"] for i in applied})

        return {
            "success": True,
            "updated_count": len(applied),
            "unchanged_count": len(prepared) - len(applied),
            "updated": applied,
            "config_version": self.version,
        }

    def reset(
        self,
        category: str | None = None,
        operator: str = "",
        operator_ip: str = "",
    ) -> dict[str, Any]:
        """重置到默认值（可按分类）"""
        if category is not None and category not in CONFIG_CATEGORIES:
            raise ConfigNotFoundError(f"配置分类不存在: {category}")

        fields = (
            CONFIG_CATEGORIES[category]["fields"]
            if category
            else sorted(UPDATABLE_FIELDS)
        )

        reset_items: list[dict[str, Any]] = []
        with self._lock:
            for field_name in fields:
                if is_sensitive(field_name) or is_readonly(field_name):
                    continue
                old_value = self.get_value(field_name)
                default_value = get_field_default(field_name)
                if old_value == default_value:
                    continue
                setattr(settings, field_name, default_value)
                now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
                self._modified[field_name] = {"at": now, "by": operator or "unknown"}
                self._version += 1
                self._last_change_at = now
                reset_items.append(
                    {
                        "field": field_name,
                        "old_value": old_value,
                        "default_value": default_value,
                    }
                )

        for item in reset_items:
            audit_store.record_change(
                config_key=item["field"],
                old_value=item["old_value"],
                new_value=item["default_value"],
                operator=operator,
                operator_ip=operator_ip,
                action="reset" if category is None else "reset_category",
                hot_applied=True,
                source="api",
            )

        if reset_items:
            with self._lock:
                self._notify_locked(
                    {i["field"]: i["default_value"] for i in reset_items}
                )

        return {
            "success": True,
            "reset_count": len(reset_items),
            "reset_fields": reset_items,
            "config_version": self.version,
        }

    # ---- 自检 ----

    def health(self) -> dict[str, Any]:
        """配置中心自身的健康状态（供 /monitoring/self-check 汇总）"""
        t0 = time.perf_counter()
        try:
            sample = self.get_value("retrieval_top_k")
            ok = sample is not None
            err = None
        except Exception as e:  # noqa: BLE001
            ok = False
            err = f"{type(e).__name__}: {e}"
        elapsed_ms = (time.perf_counter() - t0) * 1000

        with self._lock:
            return {
                "ok": ok,
                "version": self._version,
                "observers": len(self._observers),
                "modified_fields": len(self._modified),
                "last_change_at": self._last_change_at,
                "read_latency_ms": round(elapsed_ms, 3),
                "error": err,
            }


_center: ConfigCenter | None = None
_center_lock = threading.Lock()


def get_config_center() -> ConfigCenter:
    """取配置中心单例"""
    global _center
    if _center is None:
        with _center_lock:
            if _center is None:
                _center = ConfigCenter()
    return _center
