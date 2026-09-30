"""配置变更审计 —— 落库与查询

设计取舍：
    审计写入绝不能影响配置更新本身。所以：
      - 写库失败只记日志并返回 False，不向上抛（配置已经改了，不能因为审计失败就回滚）
      - 查询失败返回空列表 + 错误信息，让调用方自己判断

    敏感字段（含 key/secret/password/token）一律不落明文，old/new 都存 "[REDACTED]"。
    这与接口层的脱敏规则共用同一套关键词判断，避免两处规则漂移。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

# 敏感判定统一由 schema 提供（按 _ 切词的整词匹配），避免多处实现漂移。
from src.config_center.schema import is_sensitive as is_sensitive_key

logger = logging.getLogger(__name__)

REDACTED = "[REDACTED]"


def _to_text(value: Any) -> str:
    """把任意值转成可入库文本

    dict / list 用 JSON 保存，保证回读时可还原；其余走 str。
    None 存空串以避开列默认值带来的歧义。
    """
    if value is None:
        return ""
    if isinstance(value, dict | list | tuple):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value)


def _serialize_value(config_key: str, value: Any) -> str:
    """按脱敏规则序列化字段值"""
    if is_sensitive_key(config_key):
        # 只保留「有没有值」这一信息，不回显内容，也不回显长度
        return REDACTED if value else ""
    return _to_text(value)


def record_change(
    config_key: str,
    old_value: Any,
    new_value: Any,
    operator: str = "",
    operator_ip: str = "",
    action: str = "update",
    hot_applied: bool = True,
    source: str = "api",
    tenant_id: str = "default",
) -> bool:
    """写入一条配置变更审计记录

    Returns:
        True 写入成功；False 写入失败（已记日志，调用方无需处理）
    """
    try:
        from src.db.models import ConfigAuditLog
        from src.db.session import db_session

        entry = ConfigAuditLog(
            id=f"CFG-{uuid.uuid4().hex[:12].upper()}",
            tenant_id=tenant_id,
            config_key=config_key,
            old_value=_serialize_value(config_key, old_value),
            new_value=_serialize_value(config_key, new_value),
            action=action,
            operator=operator or "unknown",
            operator_ip=operator_ip or "",
            hot_applied=hot_applied,
            source=source,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        with db_session() as session:
            session.add(entry)
        return True
    except Exception as e:  # noqa: BLE001 - 审计失败不阻断配置变更
        logger.warning("配置审计写入失败 key=%s action=%s: %s", config_key, action, e)
        return False


def query_logs(
    config_key: str | None = None,
    limit: int = 20,
    offset: int = 0,
    operator: str | None = None,
) -> dict[str, Any]:
    """查询配置变更历史（按时间倒序）

    Returns:
        {"total": int, "items": [...], "error": Optional[str]}
        error 非空表示查询失败（例如数据库未就绪），items 为空列表。
    """
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    try:
        from src.db.models import ConfigAuditLog
        from src.db.session import db_session

        with db_session() as session:
            q = session.query(ConfigAuditLog)
            if config_key:
                q = q.filter(ConfigAuditLog.config_key == config_key)
            if operator:
                q = q.filter(ConfigAuditLog.operator == operator)
            total = q.count()
            rows = (
                q.order_by(ConfigAuditLog.created_at.desc(), ConfigAuditLog.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            items: list[dict[str, Any]] = [
                {
                    "id": r.id,
                    "config_key": r.config_key,
                    "old_value": r.old_value,
                    "new_value": r.new_value,
                    "action": r.action,
                    "operator": r.operator,
                    "operator_ip": r.operator_ip,
                    "hot_applied": bool(r.hot_applied),
                    "source": r.source,
                    "is_sensitive": is_sensitive_key(r.config_key),
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]
        return {"total": total, "items": items, "error": None}
    except Exception as e:  # noqa: BLE001 - 查询失败返回可读错误，不抛
        logger.warning("配置审计查询失败: %s", e)
        return {"total": 0, "items": [], "error": f"{type(e).__name__}: {e}"}


def count_all() -> int:
    """审计记录总数（供自检端点用）"""
    try:
        from src.db.models import ConfigAuditLog
        from src.db.session import db_session

        with db_session() as session:
            return int(session.query(ConfigAuditLog).count())
    except Exception:
        return -1


def latest_timestamp() -> str | None:
    """最近一条审计记录的时间（供自检端点判断审计链路是否活着）"""
    try:
        from src.db.models import ConfigAuditLog
        from src.db.session import db_session

        with db_session() as session:
            row = (
                session.query(ConfigAuditLog)
                .order_by(ConfigAuditLog.created_at.desc())
                .first()
            )
            return row.created_at.isoformat() if row and row.created_at else None
    except Exception:
        return None
