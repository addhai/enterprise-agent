"""配置中心 API（v1 规范路径）

与 src/api/config.py 的关系：
    src/api/config.py 是既有接口（/api/v1/admin/config/*），保持原样不动，
    以免破坏前端与既有测试。
    本模块提供任务要求的规范路径 /api/v1/config/*，能力是既有接口的超集：
      - 单字段读取/更新（原接口只能按分类读、只能批量写）
      - 范围与枚举校验（原接口只有类型转换）
      - 只读字段明确返回 400 并提示需重启（原接口静默 skip）
      - 配置变更审计与历史查询（原接口只写应用日志）
      - 热更新能力自描述（哪些字段改完即生效）
    两者共用同一个配置中心单例与同一份分类清单，不会出现两套状态。

另外提供 GET /api/v1/monitoring/self-check —— 「监控的监控」，
用于在监控自身失灵时仍能被发现。
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from src.api.rbac import Permission, require_permissions
from src.config import settings
from src.config_center import (
    ConfigError,
    ConfigNotFoundError,
    get_config_center,
)
from src.config_center import audit as audit_store
from src.config_center.categories import CONFIG_CATEGORIES
from src.config_center.schema import hot_categories, is_readonly

logger = logging.getLogger(__name__)

# 分类清单里的全部字段（用于 /config/{key} 的存在性判断）。
# 必须定义在任何请求处理之前，放在模块顶部而非文件末尾。
CONFIG_CATEGORIES_ALL_FIELDS: set = set()
for _v in CONFIG_CATEGORIES.values():
    CONFIG_CATEGORIES_ALL_FIELDS.update(_v["fields"])

# 不设 prefix，由 server.py 以 /api/v1 挂载，路径里显式写 config / monitoring
router = APIRouter(tags=["配置中心 Config Center"])


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------


class SingleUpdateRequest(BaseModel):
    """单字段更新请求"""

    value: Any = Field(..., description="新值。类型按字段定义自动校验")


class BatchUpdateRequest(BaseModel):
    """批量更新请求"""

    updates: dict[str, Any] = Field(
        ...,
        description="字段名 → 新值，如 {'retrieval_top_k': 8, 'llm_temperature': 0.2}",
    )


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    """取调用方 IP（优先取反向代理透传的真实 IP）"""
    try:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
        if request.client and request.client.host:
            return request.client.host[:64]
    except Exception as e:  # noqa: BLE001
        # 取 IP 失败不影响主流程，但要留下痕迹：审计日志里出现空 operator_ip
        # 时，能从这里查到是代理头异常还是 client 信息缺失
        logger.debug("解析调用方 IP 失败：%s", e)
    return ""


def _operator(current_user: dict[str, Any]) -> str:
    return str(
        current_user.get("user_id")
        or current_user.get("username")
        or current_user.get("sub")
        or "unknown"
    )


def _translate(exc: ConfigError) -> HTTPException:
    """配置中心异常 → HTTP 异常"""
    return HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc))


# ---------------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------------


@router.get("/config")
async def list_config(
    category: str | None = Query(None, description="按分类过滤，不传则返回全部"),
    current_user: dict[str, Any] = Depends(require_permissions(Permission.CONFIG_VIEW)),
):
    """获取配置项清单（敏感字段只返回是否已设置，不回显明文）

    返回每项含 key / type / value / default / description / readonly / hot /
    constraints / modified_at / modified_by。
    """
    center = get_config_center()
    try:
        result = center.list_fields(category)
    except ConfigNotFoundError as e:
        raise _translate(e) from e

    # 补上分类的中文标签，便于前端直接渲染
    for item in result["items"]:
        cat = CONFIG_CATEGORIES.get(item.get("category", ""), {})
        item["category_label"] = cat.get("label", "")
    result["categories"] = [
        {"key": k, "label": v["label"], "field_count": len(v["fields"])}
        for k, v in CONFIG_CATEGORIES.items()
    ]
    return result


@router.get("/config/hot-categories")
async def get_hot_categories(
    current_user: dict[str, Any] = Depends(require_permissions(Permission.CONFIG_VIEW)),
):
    """列出支持热更新的配置分类与代表字段

    用于回答「改哪些配置不需要重启」。只读字段（连接串、端口等）不出现在这里。
    """
    center = get_config_center()
    cats = hot_categories()
    detail: dict[str, list[dict[str, Any]]] = {}
    all_updatable = set()
    for _c in CONFIG_CATEGORIES.values():
        all_updatable.update(_c["fields"])
    for cat, fields in cats.items():
        # 只保留确实存在且可更新的字段，避免清单与实现脱节时返回幽灵字段
        keep = [f for f in fields if f in all_updatable]
        detail[cat] = [
            {
                "key": f,
                "value": center.mask(f, center.get_value(f)),
                "modified_at": center.describe(f).get("modified_at"),
            }
            for f in keep
        ]
    return {
        "config_version": center.version,
        "total_categories": len(cats),
        "categories": detail,
        "note": (
            "这些字段修改后立即生效，无需重启容器。"
            "启动时只读配置见各字段的 readonly 标记。"
        ),
    }


@router.get("/config/audit")
async def get_config_audit(
    key: str | None = Query(None, description="按配置项过滤"),
    operator: str | None = Query(None, description="按操作人过滤"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict[str, Any] = Depends(require_permissions(Permission.CONFIG_VIEW)),
):
    """查询配置变更历史（按时间倒序）

    敏感字段的新旧值均已脱敏为 [REDACTED]，只保留变更事实。
    """
    result = audit_store.query_logs(
        config_key=key, limit=limit, offset=offset, operator=operator
    )
    return {
        "total": result["total"],
        "limit": limit,
        "offset": offset,
        "items": result["items"],
        "query_error": result["error"],
    }


@router.get("/config/{key}")
async def get_single_config(
    key: str = Path(..., description="配置项名，如 retrieval_top_k"),
    current_user: dict[str, Any] = Depends(require_permissions(Permission.CONFIG_VIEW)),
):
    """获取单个配置项的完整描述"""
    center = get_config_center()
    if key not in CONFIG_CATEGORIES_ALL_FIELDS and not is_readonly(key):
        raise HTTPException(
            status_code=404,
            detail=f"配置项不存在: {key}。可用配置见 GET /api/v1/config",
        )
    item = center.describe(key)
    cat_key = next(
        (c for c, v in CONFIG_CATEGORIES.items() if key in v["fields"]), None
    )
    item["category"] = cat_key
    item["category_label"] = CONFIG_CATEGORIES.get(cat_key or "", {}).get("label", "")
    return item


# ---------------------------------------------------------------------------
# 配置更新
# ---------------------------------------------------------------------------


@router.put("/config/{key}")
async def update_single_config(
    request: Request,
    key: str = Path(..., description="配置项名"),
    req: SingleUpdateRequest = Body(...),
    current_user: dict[str, Any] = Depends(
        require_permissions(Permission.CONFIG_MANAGE)
    ),
):
    """更新单个配置项（改完即生效，无需重启）

    校验顺序：只读检查 → 白名单检查 → 类型转换 → 范围/枚举校验。
    任一环节失败返回 400 或 404，并给出可读原因。
    """
    center = get_config_center()
    try:
        result = center.set_value(
            key,
            req.value,
            operator=_operator(current_user),
            operator_ip=_client_ip(request),
        )
    except ConfigError as e:
        raise _translate(e) from e
    result["hot_applied"] = True
    return result


@router.patch("/config/batch")
async def update_batch_config(
    request: Request,
    req: BatchUpdateRequest = Body(...),
    current_user: dict[str, Any] = Depends(
        require_permissions(Permission.CONFIG_MANAGE)
    ),
):
    """批量更新配置（全量校验通过后才应用）

    注意语义：只要有一项不合法，整批拒绝、不做任何修改。
    这样可以避免「改了一半」的中间态被误认为已全部生效。
    """
    center = get_config_center()
    try:
        result = center.set_batch(
            req.updates,
            operator=_operator(current_user),
            operator_ip=_client_ip(request),
        )
    except ConfigError as e:
        raise _translate(e) from e
    result["hot_applied"] = True
    return result


@router.post("/config/reset")
async def reset_config(
    request: Request,
    category: str | None = Query(None, description="只重置某个分类，不传则重置全部"),
    current_user: dict[str, Any] = Depends(
        require_permissions(Permission.CONFIG_MANAGE)
    ),
):
    """把配置重置为默认值（用于出错后回滚）"""
    center = get_config_center()
    try:
        return center.reset(
            category=category,
            operator=_operator(current_user),
            operator_ip=_client_ip(request),
        )
    except ConfigError as e:
        raise _translate(e) from e


# ---------------------------------------------------------------------------
# 监控自检（监控的监控）
# ---------------------------------------------------------------------------


def _check_metrics() -> dict[str, Any]:
    """指标采集链路是否活着"""
    try:
        from src.api.monitoring import get_scrape_status

        st = get_scrape_status()
        age = st["seconds_since_last_scrape"]
        return {
            "ok": bool(st["scrape_count"] > 0),
            "last_scrape_at": st["last_scrape_at"],
            "seconds_since_last_scrape": age,
            "scrape_count": st["scrape_count"],
            "endpoint": "/api/v1/metrics/prometheus",
            "hint": (
                "从未被抓取，检查 Prometheus 的 scrape_configs 是否指向本路径"
                if not st["scrape_count"]
                else None
            ),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _check_logs() -> dict[str, Any]:
    """结构化日志是否在正常落盘"""
    log_dir = os.getenv("LOG_DIR", "/app/logs")
    path = os.path.join(log_dir, "app.jsonl")
    try:
        if not os.path.exists(path):
            return {
                "ok": False,
                "path": path,
                "error": "日志文件不存在",
                "hint": "确认容器入口调用了 setup_logging()，且 LOG_DIR 可写",
            }
        stat = os.stat(path)
        age = round(time.time() - stat.st_mtime, 1)
        with open(path, encoding="utf-8", errors="replace") as fh:
            last_line = ""
            line_count = 0
            for line in fh:
                line_count += 1
                if line.strip():
                    last_line = line.strip()
        sample = None
        try:
            import json as _json

            sample = _json.loads(last_line) if last_line else None
        except Exception:
            sample = None
        return {
            "ok": True,
            "path": path,
            "size_bytes": stat.st_size,
            "lines": line_count,
            "seconds_since_last_write": age,
            "last_record_keys": sorted(sample.keys())
            if isinstance(sample, dict)
            else None,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "path": path, "error": f"{type(e).__name__}: {e}"}


def _check_dependencies() -> dict[str, Any]:
    """各依赖组件状态（带超时，单个失败不影响其它）"""
    checks: dict[str, Any] = {}

    # 数据库
    t0 = time.perf_counter()
    try:
        from sqlalchemy import text

        from src.db.session import db_session

        with db_session() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = {
            "ok": True,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
    except Exception as e:  # noqa: BLE001
        checks["database"] = {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:150]}",
        }

    # Redis
    t0 = time.perf_counter()
    try:
        import redis  # type: ignore

        from src.config import settings as _s

        client = redis.from_url(
            _s.redis_url, socket_connect_timeout=2, socket_timeout=2
        )
        client.ping()
        checks["redis"] = {
            "ok": True,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
    except Exception as e:  # noqa: BLE001
        checks["redis"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}

    # 向量库
    t0 = time.perf_counter()
    try:
        from src.api.dependencies import get_retriever

        r = get_retriever()
        vs = getattr(r, "vector_store", None)
        count = None
        try:
            count = vs.count() if vs is not None and hasattr(vs, "count") else None
        except Exception:
            count = None
        checks["vector_store"] = {
            "ok": r is not None,
            "backend": getattr(r, "backend", "unknown"),
            "documents": count,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
    except Exception as e:  # noqa: BLE001
        checks["vector_store"] = {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:150]}",
        }

    # 推理服务（本地 ollama 的 OpenAI 兼容端点）
    t0 = time.perf_counter()
    try:
        import json as _json
        import urllib.parse
        import urllib.request

        url = settings.openai_api_base.rstrip("/") + "/models"
        # 显式限定协议：openai_api_base 来自启动配置，若被误配成 file:// 或
        # 自定义 scheme，urlopen 会去读本地文件而不报错。这里提前拦掉，
        # 让误配在自检阶段就暴露，而不是变成一个"看起来正常"的假绿灯。
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            raise ValueError(f"openai_api_base 协议非法（需 http/https）：{url}")
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310 (协议已校验)
            payload = _json.loads(resp.read().decode("utf-8", "replace"))
        models = [m.get("id") for m in payload.get("data", [])]
        checks["llm_backend"] = {
            "ok": True,
            "url": url,
            "models": models[:5],
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
    except Exception as e:  # noqa: BLE001
        checks["llm_backend"] = {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:150]}",
        }

    return checks


@router.get("/monitoring/self-check")
async def monitoring_self_check(
    current_user: dict[str, Any] = Depends(require_permissions(Permission.CONFIG_VIEW)),
):
    """监控自检 —— 当监控自身失灵时能被发现

    回答三个问题：
      1. 指标还在被采集吗（最近一次被抓取是什么时候）
      2. 日志还在写吗（文件是否增长、最后一条记录长什么样）
      3. 配置中心与各依赖是否健康

    整体 ok 的判定：指标在采集 + 日志在写 + 配置中心可读 + 数据库可连。
    向量库与推理服务失败会体现在 details 里，但不一定判整机不健康
    （它们可以降级，而指标与日志断了就等于失去观察能力）。
    """
    t0 = time.perf_counter()

    metrics = _check_metrics()
    logs = _check_logs()
    try:
        config_health = get_config_center().health()
        # 补上「可热更字段清单」与只读字段计数。
        # 自检的用途是「一眼看出配置中心当前能管什么」：
        # 只给版本号不够，运维还需要知道哪些字段改完即生效、哪些必须重启。
        # 完整清单（含每项当前值）仍由 GET /api/v1/config/hot-categories 提供。
        from src.config_center.schema import hot_categories

        readonly_keys = sorted(
            f for f in CONFIG_CATEGORIES_ALL_FIELDS if is_readonly(f)
        )
        hot = hot_categories()
        config_health["hot_categories"] = {
            cat: sorted(f for f in fields if f in CONFIG_CATEGORIES_ALL_FIELDS)
            for cat, fields in hot.items()
        }
        config_health["hot_field_count"] = sum(
            len(v) for v in config_health["hot_categories"].values()
        )
        config_health["readonly_field_count"] = len(readonly_keys)
        config_health["total_managed_fields"] = len(CONFIG_CATEGORIES_ALL_FIELDS)
    except Exception as e:  # noqa: BLE001
        config_health = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    deps = _check_dependencies()

    core_ok = bool(
        metrics.get("ok")
        and logs.get("ok")
        and config_health.get("ok")
        and deps.get("database", {}).get("ok")
    )

    observations: list[str] = []
    if not metrics.get("ok"):
        observations.append("指标端点从未被抓取，Prometheus 抓取链路可能未生效")
    if not logs.get("ok"):
        observations.append("结构化日志未正常落盘，排查时可能缺少现场")
    if not config_health.get("ok"):
        observations.append("配置中心不可读")
    if not deps.get("database", {}).get("ok"):
        observations.append("数据库不可达，审计与业务数据会受影响")
    # 可降级依赖：不阻断服务，但要在自检结果里点名，避免"看起来一切正常"
    observations.extend(
        f"{name} 不可用（可降级，但会影响相应功能）"
        for name in ("redis", "vector_store", "llm_backend")
        if not deps.get(name, {}).get("ok")
    )

    return {
        "ok": core_ok,
        "checked_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
        "checks": {
            "metrics": metrics,
            "logs": logs,
            "config_center": config_health,
            "dependencies": deps,
        },
        "audit_records": audit_store.count_all(),
        "latest_audit_at": audit_store.latest_timestamp(),
        "observations": observations,
    }
