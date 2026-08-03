"""Repository 层 — 同步 DB 访问函数

设计：
    - 全部为同步函数，内部用 db_session() 上下文管理器
    - 直接接收 / 返回现有业务 Pydantic 模型（KBSet / KBItem / Ticket 等）或 dict，
      调用点（knowledge.py / mcp_tools/kb.py / auth.py 等）几乎无需改写逻辑
    - 业务模块（KBSet 等）按需延迟导入，避免顶层循环依赖
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from src.db.base import Base
from src.db.engine import get_engine
from src.db.models import (
    Conversation,
    KbDocument,
    KnowledgeBase,
    Message,
    Notification,
    Satisfaction,
    Ticket,
    User,
)
from src.db.session import db_session

logger = logging.getLogger(__name__)

DEFAULT_TENANT = "default"


# ---------------------------------------------------------------------------
# 通用 helpers
# ---------------------------------------------------------------------------

def _loads(s: Optional[str], default: Any) -> Any:
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


def _dumps(v: Any) -> str:
    return json.dumps(v or [], ensure_ascii=False)


def _dt2f(dt: Optional[datetime]) -> float:
    if dt is None:
        return 0.0
    return dt.replace(tzinfo=timezone.utc).timestamp()


def _f2dt(f: Optional[float]) -> datetime:
    if not f:
        return datetime.utcnow()
    try:
        return datetime.utcfromtimestamp(float(f))
    except Exception:
        return datetime.utcnow()


def _iso2dt(s: Optional[str]) -> datetime:
    if not s:
        return datetime.utcnow()
    try:
        s2 = s.replace("Z", "+00:00") if isinstance(s, str) and s.endswith("Z") else s
        return datetime.fromisoformat(s2)
    except Exception:
        try:
            return _f2dt(float(s))
        except Exception:
            return datetime.utcnow()


def _dt2iso(dt: Optional[datetime]) -> str:
    return (dt or datetime.utcnow()).isoformat()


# ---------------------------------------------------------------------------
# 用户（合并原 auth._users 与 mcp_tools/users 双存储）
# ---------------------------------------------------------------------------

def _user_row_to_dict(row: User) -> Dict[str, Any]:
    username = row.username
    return {
        "user_id": row.id,
        "username": username,
        "avatar": (username[0].upper() if username else "?"),
        "role": row.role,
        "status": row.status,
        "is_admin": bool(row.is_admin),
        "email": row.email,
        "department": row.department,
        "created_at": _dt2f(row.created_at),
        "display_name": row.display_name or username,
    }


def user_get_by_username(username: str) -> Optional[Dict[str, Any]]:
    with db_session() as s:
        row = s.query(User).filter(User.username == username).first()
        return _user_row_to_dict(row) if row else None


def user_get_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    with db_session() as s:
        row = s.query(User).filter(User.id == user_id).first()
        return _user_row_to_dict(row) if row else None


def user_create(user_dict: Dict[str, Any]) -> Dict[str, Any]:
    with db_session() as s:
        row = User(
            id=user_dict["user_id"],
            tenant_id=user_dict.get("tenant_id", DEFAULT_TENANT),
            username=user_dict["username"],
            password_hash=user_dict.get("password_hash", ""),
            display_name=user_dict.get("display_name", user_dict.get("username", "")),
            email=user_dict.get("email", ""),
            role=user_dict.get("role", "viewer"),
            status=user_dict.get("status", "active"),
            is_admin=user_dict.get("is_admin", False),
            department=user_dict.get("department", ""),
            created_at=_f2dt(user_dict.get("created_at")),
        )
        s.add(row)
    return user_get_by_id(user_dict["user_id"])


def user_update(user_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with db_session() as s:
        row = s.query(User).filter(User.id == user_id).first()
        if row is None:
            return None
        for key in ("username", "password_hash", "display_name", "email",
                    "role", "status", "is_admin", "department"):
            if key in data:
                setattr(row, key, data[key])
    return user_get_by_id(user_id)


def list_users() -> List[Dict[str, Any]]:
    with db_session() as s:
        rows = s.query(User).order_by(User.created_at.desc()).all()
        return [_user_row_to_dict(r) for r in rows]


def ensure_default_users(defaults: List[Dict[str, Any]]) -> None:
    """若默认账号不存在则创建。defaults 为含 user_id/username/password_hash/role 的 dict 列表。"""
    for d in defaults:
        with db_session() as s:
            exists = s.query(User).filter(User.username == d["username"]).first()
            if exists is None:
                s.add(User(
                    id=d["user_id"],
                    tenant_id=DEFAULT_TENANT,
                    username=d["username"],
                    password_hash=d["password_hash"],
                    display_name=d.get("display_name", d["username"]),
                    email=d.get("email", ""),
                    role=d.get("role", "viewer"),
                    status=d.get("status", "active"),
                    is_admin=d.get("is_admin", False),
                    department=d.get("department", ""),
                    created_at=datetime.utcnow(),
                ))
                logger.info("Seeded default user: %s", d["username"])


# ---------------------------------------------------------------------------
# 知识库集合（KBSet）
# ---------------------------------------------------------------------------

def _row_to_kb_set(row: KnowledgeBase):
    """把 DB 行转为 knowledge.KBSet 对象（供 knowledge.py / 适配器使用）"""
    from src.api.knowledge import KBSet
    from src.mcp_tools.kb import KBType, KBVersion
    return KBSet(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description or "",
        kb_version=KBVersion(row.kb_version),
        kb_type=KBType(row.kb_type),
        similarity_threshold=row.similarity_threshold,
        weight=row.weight,
        document_count=row.document_count,
        total_chunks=row.total_chunks,
        created_at=_dt2iso(row.created_at),
        updated_at=_dt2iso(row.updated_at),
        created_by=row.created_by or "",
    )


def kb_set_save(kb: Any) -> Any:
    """upsert 一个 KBSet（接收 knowledge.py 的 KBSet 模型）。"""
    from src.mcp_tools.kb import KBType, KBVersion
    tenant_id = getattr(kb, "tenant_id", DEFAULT_TENANT)
    kb_version = kb.kb_version.value if hasattr(kb.kb_version, "value") else kb.kb_version
    kb_type = kb.kb_type.value if hasattr(kb.kb_type, "value") else kb.kb_type
    with db_session() as s:
        row = s.query(KnowledgeBase).filter(KnowledgeBase.id == kb.id).first()
        if row is None:
            row = KnowledgeBase(id=kb.id)
            s.add(row)
        row.tenant_id = tenant_id
        row.name = kb.name
        row.description = kb.description or ""
        row.kb_version = kb_version
        row.kb_type = kb_type
        row.similarity_threshold = kb.similarity_threshold
        row.weight = kb.weight
        row.document_count = kb.document_count
        row.total_chunks = kb.total_chunks
        row.created_by = getattr(kb, "created_by", "") or ""
        row.created_at = _iso2dt(getattr(kb, "created_at", None))
        row.updated_at = _iso2dt(getattr(kb, "updated_at", None))
    return kb


def kb_set_get(tenant_id: str, kb_id: str) -> Optional[Any]:
    with db_session() as s:
        row = (s.query(KnowledgeBase)
               .filter(KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.id == kb_id)
               .first())
        if row is None:
            return None
        return _row_to_kb_set(row)


def kb_set_list(tenant_id: str) -> List[Any]:
    with db_session() as s:
        rows = (s.query(KnowledgeBase)
                .filter(KnowledgeBase.tenant_id == tenant_id)
                .order_by(KnowledgeBase.created_at.desc()).all())
        return [_row_to_kb_set(r) for r in rows]


def kb_set_delete(tenant_id: str, kb_id: str) -> bool:
    with db_session() as s:
        row = (s.query(KnowledgeBase)
               .filter(KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.id == kb_id)
               .first())
        if row is None:
            return False
        s.delete(row)
    return True


def kb_set_reset() -> None:
    """测试用：清空 knowledge_bases 表"""
    with db_session() as s:
        s.query(KnowledgeBase).delete()


# ---------------------------------------------------------------------------
# 知识库文档（KBItem）
# ---------------------------------------------------------------------------

def _row_to_kb_item(row: KbDocument):
    """把 DB 行转为 mcp_tools.kb.KBItem 对象（供 mcp_tools/kb.py / 适配器使用）"""
    from src.mcp_tools.kb import (
        KBItem,
        KBItemStatus,
        KBType,
        KBVersion,
        UploadMethod,
    )
    return KBItem(
        id=row.id,
        tenant_id=row.tenant_id,
        title=row.title,
        file_path=row.file_path,
        source_type=row.source_type,
        status=KBItemStatus(row.status),
        chunk_count=row.chunk_count,
        indexed_at=_dt2iso(row.indexed_at) if row.indexed_at else None,
        created_at=_dt2iso(row.created_at),
        kb_version=KBVersion(row.kb_version),
        kb_type=KBType(row.kb_type),
        doc_format=row.doc_format,
        kb_id=row.kb_id,
        upload_method=UploadMethod(row.upload_method),
        file_size=row.file_size,
        parse_status=row.parse_status,
        similarity_threshold=row.similarity_threshold,
        weight=row.weight,
    )


def kb_item_save(item: Any) -> Any:
    tenant_id = getattr(item, "tenant_id", DEFAULT_TENANT)
    with db_session() as s:
        row = s.query(KbDocument).filter(KbDocument.id == item.id).first()
        if row is None:
            row = KbDocument(id=item.id)
            s.add(row)
        row.tenant_id = tenant_id
        row.kb_id = getattr(item, "kb_id", "")
        row.title = getattr(item, "title", "")
        row.file_path = getattr(item, "file_path", "")
        row.source_type = getattr(item, "source_type", "document")
        row.status = getattr(item, "status", "pending").value if hasattr(getattr(item, "status", "pending"), "value") else getattr(item, "status", "pending")
        row.chunk_count = getattr(item, "chunk_count", 0)
        row.indexed_at = _iso2dt(getattr(item, "indexed_at", None)) if getattr(item, "indexed_at", None) else None
        row.created_at = _iso2dt(getattr(item, "created_at", None))
        row.kb_version = getattr(item, "kb_version", "standard").value if hasattr(getattr(item, "kb_version", "standard"), "value") else getattr(item, "kb_version", "standard")
        row.kb_type = getattr(item, "kb_type", "document").value if hasattr(getattr(item, "kb_type", "document"), "value") else getattr(item, "kb_type", "document")
        row.upload_method = getattr(item, "upload_method", "single").value if hasattr(getattr(item, "upload_method", "single"), "value") else getattr(item, "upload_method", "single")
        row.file_size = getattr(item, "file_size", 0)
        row.doc_format = getattr(item, "doc_format", "")
        row.parse_status = getattr(item, "parse_status", "pending")
        row.similarity_threshold = getattr(item, "similarity_threshold", 0.2)
        row.weight = getattr(item, "weight", 1.0)
    return item


def kb_item_get(tenant_id: str, doc_id: str) -> Optional[Any]:
    with db_session() as s:
        row = (s.query(KbDocument)
               .filter(KbDocument.tenant_id == tenant_id, KbDocument.id == doc_id)
               .first())
        return _row_to_kb_item(row) if row else None


def kb_item_list(tenant_id: str, limit: int = 1000) -> List[Any]:
    with db_session() as s:
        rows = (s.query(KbDocument)
                .filter(KbDocument.tenant_id == tenant_id)
                .order_by(KbDocument.created_at.desc()).limit(limit).all())
        return [_row_to_kb_item(r) for r in rows]


def kb_item_list_by_kb(tenant_id: str, kb_id: str) -> List[Any]:
    with db_session() as s:
        rows = (s.query(KbDocument)
                .filter(KbDocument.tenant_id == tenant_id, KbDocument.kb_id == kb_id)
                .order_by(KbDocument.created_at.desc()).all())
        return [_row_to_kb_item(r) for r in rows]


def kb_item_delete(tenant_id: str, doc_id: str) -> bool:
    with db_session() as s:
        row = (s.query(KbDocument)
               .filter(KbDocument.tenant_id == tenant_id, KbDocument.id == doc_id)
               .first())
        if row is None:
            return False
        s.delete(row)
    return True


def kb_item_reset() -> None:
    """测试用：清空 kb_documents 表"""
    with db_session() as s:
        s.query(KbDocument).delete()


# ---------------------------------------------------------------------------
# 工单（Ticket）— 实现 TicketStore Protocol
# ---------------------------------------------------------------------------

def _ticket_row_to_model(row: Ticket):
    from src.ticket.models import Comment, Ticket as TicketModel, TicketStatus
    comments = [Comment(**c) for c in _loads(row.comments_json, [])]
    return TicketModel(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        title=row.title,
        description=row.description or "",
        category=row.category,
        priority=row.priority,
        status=row.status,
        assignee=row.assignee,
        tags=_loads(row.tags_json, []),
        comments=comments,
        idempotency_key=row.idempotency_key,
        created_at=row.created_at or datetime.utcnow(),
        updated_at=row.updated_at or datetime.utcnow(),
        closed_at=row.closed_at,
    )


def ticket_create(req) -> Any:
    from src.ticket.models import Ticket as TicketModel
    ticket = TicketModel(
        tenant_id=req.tenant_id,
        user_id=req.user_id,
        title=req.title,
        description=req.description,
        category=req.category,
        priority=req.priority,
        tags=list(req.tags),
        idempotency_key=req.idempotency_key,
    )
    with db_session() as s:
        # 幂等检查
        if req.idempotency_key:
            existing = (s.query(Ticket)
                        .filter(Ticket.tenant_id == req.tenant_id,
                                Ticket.idempotency_key == req.idempotency_key)
                        .first())
            if existing:
                return _ticket_row_to_model(existing)
        row = Ticket(
            id=ticket.id,
            tenant_id=ticket.tenant_id,
            user_id=ticket.user_id,
            title=ticket.title,
            description=ticket.description,
            category=ticket.category.value if hasattr(ticket.category, "value") else ticket.category,
            priority=ticket.priority.value if hasattr(ticket.priority, "value") else ticket.priority,
            status=ticket.status.value if hasattr(ticket.status, "value") else ticket.status,
            assignee=ticket.assignee,
            tags_json=_dumps(ticket.tags),
            idempotency_key=ticket.idempotency_key,
            comments_json=_dumps([]),
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )
        s.add(row)
    return ticket


def ticket_get(ticket_id: str, tenant_id: str) -> Optional[Any]:
    with db_session() as s:
        row = (s.query(Ticket)
               .filter(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
               .first())
        return _ticket_row_to_model(row) if row else None


def ticket_update(ticket_id: str, tenant_id: str, req) -> Optional[Any]:
    from src.ticket.models import TicketStatus
    with db_session() as s:
        row = (s.query(Ticket)
               .filter(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
               .first())
        if row is None:
            return None
        if row.status in (TicketStatus.CLOSED.value, TicketStatus.CANCELLED.value):
            return None
        for field, attr in (("title", "title"), ("description", "description"),
                            ("category", "category"), ("priority", "priority"),
                            ("status", "status"), ("assignee", "assignee"),
                            ("tags", "tags")):
            value = getattr(req, field, None)
            if value is not None:
                if field in ("category", "priority", "status"):
                    setattr(row, field, value.value if hasattr(value, "value") else value)
                elif field == "tags":
                    setattr(row, "tags_json", _dumps(list(value)))
                else:
                    setattr(row, field, value)
        if getattr(req, "status", None) in (TicketStatus.CLOSED, TicketStatus.CANCELLED):
            from datetime import timezone
            row.closed_at = datetime.now(timezone.utc)
        row.updated_at = datetime.utcnow()
    return ticket_get(ticket_id, tenant_id)


def ticket_list(filter) -> List[Any]:
    with db_session() as s:
        q = s.query(Ticket)
        if filter.tenant_id:
            q = q.filter(Ticket.tenant_id == filter.tenant_id)
        if filter.user_id:
            q = q.filter(Ticket.user_id == filter.user_id)
        if filter.status:
            st = filter.status.value if hasattr(filter.status, "value") else filter.status
            q = q.filter(Ticket.status == st)
        if filter.category:
            cat = filter.category.value if hasattr(filter.category, "value") else filter.category
            q = q.filter(Ticket.category == cat)
        if filter.priority:
            pr = filter.priority.value if hasattr(filter.priority, "value") else filter.priority
            q = q.filter(Ticket.priority == pr)
        if filter.assignee:
            q = q.filter(Ticket.assignee == filter.assignee)
        rows = q.order_by(Ticket.created_at.desc()).limit(filter.limit).all()
        return [_ticket_row_to_model(r) for r in rows]


def ticket_add_comment(ticket_id: str, tenant_id: str, comment) -> Optional[Any]:
    with db_session() as s:
        row = (s.query(Ticket)
               .filter(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
               .first())
        if row is None:
            return None
        comments = _loads(row.comments_json, [])
        comments.append({
            "id": getattr(comment, "id", ""),
            "author": getattr(comment, "author", ""),
            "content": getattr(comment, "content", ""),
            "created_at": getattr(comment, "created_at", datetime.utcnow()).isoformat()
            if hasattr(getattr(comment, "created_at", None), "isoformat") else str(getattr(comment, "created_at", "")),
        })
        row.comments_json = _dumps(comments)
        row.updated_at = datetime.utcnow()
    return ticket_get(ticket_id, tenant_id)


def ticket_delete(ticket_id: str, tenant_id: str) -> bool:
    with db_session() as s:
        row = (s.query(Ticket)
               .filter(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
               .first())
        if row is None:
            return False
        s.delete(row)
    return True


def ticket_reset() -> None:
    """测试用：清空工单表"""
    with db_session() as s:
        s.query(Ticket).delete()


# ---------------------------------------------------------------------------
# 满意度（Satisfaction）
# ---------------------------------------------------------------------------

def satisfaction_create(record: Dict[str, Any]) -> Dict[str, Any]:
    with db_session() as s:
        row = Satisfaction(
            id=record["id"],
            tenant_id=DEFAULT_TENANT,
            session_id=record.get("session_id", ""),
            user_id=record.get("user_id", ""),
            score=record.get("score", 0),
            tags_json=_dumps(record.get("tags", [])),
            comment=record.get("comment", ""),
            agent_id=record.get("agent_id"),
            created_at=_f2dt(record.get("created_at")),
        )
        s.add(row)
    return record


def satisfaction_list(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    with db_session() as s:
        q = s.query(Satisfaction)
        if user_id:
            q = q.filter(Satisfaction.user_id == user_id)
        if session_id:
            q = q.filter(Satisfaction.session_id == session_id)
        if agent_id:
            q = q.filter(Satisfaction.agent_id == agent_id)
        rows = q.order_by(Satisfaction.created_at.desc()).limit(limit).all()
        return [{
            "id": r.id,
            "session_id": r.session_id,
            "user_id": r.user_id,
            "score": r.score,
            "tags": _loads(r.tags_json, []),
            "comment": r.comment,
            "agent_id": r.agent_id,
            "created_at": _dt2f(r.created_at),
        } for r in rows]


def satisfaction_count_since(cutoff_float: float) -> int:
    with db_session() as s:
        cutoff = _f2dt(cutoff_float)
        return s.query(func.count(Satisfaction.id)).filter(
            Satisfaction.created_at >= cutoff).scalar() or 0


# ---------------------------------------------------------------------------
# 通知（Notification）
# ---------------------------------------------------------------------------

def notification_create(record: Dict[str, Any]) -> Dict[str, Any]:
    with db_session() as s:
        row = Notification(
            id=record["id"],
            tenant_id=DEFAULT_TENANT,
            type=record.get("type", ""),
            level=record.get("level", "info"),
            title=record.get("title", ""),
            message=record.get("message", ""),
            target_roles_json=_dumps(record.get("target_roles", [])),
            target_users_json=_dumps(record.get("target_users", [])),
            link=record.get("link"),
            read_by_json=_dumps(record.get("read_by", [])),
            created_at=_f2dt(record.get("created_at")),
        )
        s.add(row)
    return record


def notification_list_all(limit: int = 500) -> List[Dict[str, Any]]:
    with db_session() as s:
        rows = s.query(Notification).order_by(
            Notification.created_at.desc()).limit(limit).all()
        return [_note_row_to_dict(r) for r in rows]


def _note_row_to_dict(r: Notification) -> Dict[str, Any]:
    return {
        "id": r.id,
        "type": r.type,
        "level": r.level,
        "title": r.title,
        "message": r.message,
        "target_roles": _loads(r.target_roles_json, []),
        "target_users": _loads(r.target_users_json, []),
        "link": r.link,
        "read_by": _loads(r.read_by_json, []),
        "created_at": _dt2f(r.created_at),
    }


def notification_mark_read(notification_id: str, user_id: str) -> bool:
    with db_session() as s:
        row = s.query(Notification).filter(Notification.id == notification_id).first()
        if row is None:
            return False
        read_by = _loads(row.read_by_json, [])
        if user_id not in read_by:
            read_by.append(user_id)
            row.read_by_json = _dumps(read_by)
    return True


def notification_mark_all_read_for(user_id: str, role: str, username: str) -> int:
    updated = 0
    with db_session() as s:
        rows = s.query(Notification).all()
        for r in rows:
            visible = _note_visible(r, user_id, role, username)
            read_by = _loads(r.read_by_json, [])
            if visible and user_id not in read_by:
                read_by.append(user_id)
                r.read_by_json = _dumps(read_by)
                updated += 1
    return updated


def _note_visible(r: Notification, user_id: str, role: str, username: str) -> bool:
    target_users = _loads(r.target_users_json, [])
    target_roles = _loads(r.target_roles_json, [])
    if target_users:
        if username in target_users or user_id in target_users:
            return True
        return False
    if target_roles:
        return role in target_roles
    return True


# ---------------------------------------------------------------------------
# 会话 / 消息（WebSocket 对话持久化）
# ---------------------------------------------------------------------------

def conversation_ensure(
    session_id: str,
    tenant_id: str,
    user_id: str,
    channel: str = "web",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """确保会话存在（不存在则创建），返回 conversation id (= session_id)。"""
    with db_session() as s:
        row = s.query(Conversation).filter(Conversation.id == session_id).first()
        if row is None:
            row = Conversation(
                id=session_id,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                channel=channel,
                metadata_json=_dumps(metadata or {}),
            )
            s.add(row)
        else:
            row.updated_at = datetime.utcnow()
    return session_id


def message_save(
    session_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    content: str,
    intent: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    message_id: Optional[str] = None,
) -> None:
    """持久化一条消息到 messages 表（不阻塞 WS 流式推送）。"""
    import uuid
    with db_session() as s:
        row = Message(
            id=message_id or f"MSG-{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            conversation_id=session_id,
            role=role,
            content=content,
            intent=intent,
            metadata_json=_dumps(metadata or {}),
        )
        s.add(row)
        conv = s.query(Conversation).filter(Conversation.id == session_id).first()
        if conv is not None:
            conv.updated_at = datetime.utcnow()


def message_list(session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    with db_session() as s:
        rows = (s.query(Message)
                .filter(Message.conversation_id == session_id)
                .order_by(Message.created_at.asc()).limit(limit).all())
        return [{
            "id": r.id,
            "role": r.role,
            "content": r.content,
            "intent": r.intent,
            "metadata": _loads(r.metadata_json, {}),
            "created_at": _dt2f(r.created_at),
        } for r in rows]


def conversation_list(
    tenant_id: str = DEFAULT_TENANT,
    user_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    with db_session() as s:
        q = s.query(Conversation).filter(Conversation.tenant_id == tenant_id)
        if user_id:
            q = q.filter(Conversation.user_id == user_id)
        rows = q.order_by(Conversation.updated_at.desc()).limit(limit).all()
        result = []
        for r in rows:
            last = (s.query(Message)
                    .filter(Message.conversation_id == r.id)
                    .order_by(Message.created_at.desc()).first())
            result.append({
                "session_id": r.session_id or r.id,
                "user_id": r.user_id,
                "channel": r.channel,
                "status": r.status,
                "message_count": s.query(func.count(Message.id))
                .filter(Message.conversation_id == r.id).scalar() or 0,
                "last_message": last.content[:200] if last else "",
                "updated_at": _dt2f(r.updated_at),
            })
        return result


def conversation_delete(session_id: str) -> bool:
    """删除会话及其全部消息（管理员清理数据用）。返回是否存在并删除。"""
    with db_session() as s:
        msgs = s.query(Message).filter(Message.conversation_id == session_id).all()
        for m in msgs:
            s.delete(m)
        conv = s.query(Conversation).filter(Conversation.id == session_id).first()
        if conv is None:
            return False
        s.delete(conv)
    return True
