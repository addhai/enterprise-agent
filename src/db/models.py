"""SQLAlchemy ORM 模型 — 核心业务实体的持久化映射

设计约定：
    - 主键全部为 String（与现有业务 ID 格式一致：KBS-xxx / KB-xxx / TKT-xxx / SAT-xxx / NOT-xxx / 用户名ID）
    - tenant_id 统一为 String（默认 "default"），不强制外键（运行时代码无租户概念）
    - 所有表带 created_at / updated_at（UTC DateTime）
    - JSON 类字段（tags / metadata / comments 等）用 Text 存储，由 repository 层做 json 序列化，
      以保证 Postgres 与 SQLite 双后端行为一致
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)

from src.db.base import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class User(Base):
    """用户（合并原 auth._users 与 mcp_tools/users 双存储）"""
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)            # user_id
    tenant_id = Column(String(64), default="default", index=True)
    username = Column(String(200), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(200), default="")
    email = Column(String(320), default="")
    role = Column(String(32), default="viewer")
    status = Column(String(32), default="active")
    is_admin = Column(Boolean, default=False)
    department = Column(String(200), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class KnowledgeBase(Base):
    """知识库集合（对应 KBSet）"""
    __tablename__ = "knowledge_bases"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), default="default", index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    kb_version = Column(String(32), default="standard")
    kb_type = Column(String(32), default="document")
    similarity_threshold = Column(Float, default=0.2)
    weight = Column(Float, default=1.0)
    document_count = Column(Integer, default=0)
    total_chunks = Column(Integer, default=0)
    status = Column(String(32), default="active")
    created_by = Column(String(64), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class KbDocument(Base):
    """知识库文档（对应 KBItem）"""
    __tablename__ = "kb_documents"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), default="default", index=True)
    kb_id = Column(String(64), default="", index=True)
    title = Column(String(500), default="")
    file_path = Column(Text, default="")
    source_type = Column(String(32), default="document")
    status = Column(String(32), default="pending")
    chunk_count = Column(Integer, default=0)
    indexed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    kb_version = Column(String(32), default="standard")
    kb_type = Column(String(32), default="document")
    doc_format = Column(String(32), default="")
    upload_method = Column(String(32), default="single")
    file_size = Column(BigInteger, default=0)
    parse_status = Column(String(32), default="pending")
    similarity_threshold = Column(Float, default=0.2)
    weight = Column(Float, default=1.0)


class Conversation(Base):
    """对话会话（对应 WebSocket SessionState）"""
    __tablename__ = "conversations"

    id = Column(String(64), primary_key=True)           # = session_id
    tenant_id = Column(String(64), default="default", index=True)
    user_id = Column(String(64), default="", index=True)
    session_id = Column(String(100), default="")
    channel = Column(String(50), default="web")
    status = Column(String(32), default="active")
    metadata_json = Column(Text, default="{}")          # JSON 字符串
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Message(Base):
    """对话消息（对应 SessionState.conversation_history 中的一条）"""
    __tablename__ = "messages"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), default="default", index=True)
    conversation_id = Column(String(64), default="", index=True)  # = session_id
    role = Column(String(32), nullable=False)
    content = Column(Text, default="")
    intent = Column(String(64), default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow)


class Ticket(Base):
    """工单"""
    __tablename__ = "tickets"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), default="default", index=True)
    user_id = Column(String(64), default="", index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    category = Column(String(64), default="other")
    priority = Column(String(32), default="medium")
    status = Column(String(32), default="open")
    assignee = Column(String(64), nullable=True)
    tags_json = Column(Text, default="[]")              # JSON 字符串
    idempotency_key = Column(String(255), nullable=True, index=True)
    comments_json = Column(Text, default="[]")          # JSON 字符串
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    closed_at = Column(DateTime, nullable=True)


class Satisfaction(Base):
    """满意度评价记录"""
    __tablename__ = "satisfaction"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), default="default", index=True)
    session_id = Column(String(100), default="", index=True)
    user_id = Column(String(64), default="", index=True)
    score = Column(Integer, default=0)
    tags_json = Column(Text, default="[]")
    comment = Column(Text, default="")
    agent_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class Notification(Base):
    """站内通知"""
    __tablename__ = "notifications"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), default="default", index=True)
    type = Column(String(64), default="")
    level = Column(String(32), default="info")
    title = Column(String(500), default="")
    message = Column(Text, default="")
    target_roles_json = Column(Text, default="[]")
    target_users_json = Column(Text, default="[]")
    link = Column(String(500), nullable=True)
    read_by_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=_utcnow)


class Tenant(Base):
    """租户（多租户隔离的根级单元）

    一个租户 = 一个独立的数据空间，其下的用户 / 工单 / 知识库 / 会话彼此不可见。
    id 即 tenant_id 字符串（如 "default" / "acme" / "globex"）。
    """
    __tablename__ = "tenants"

    id = Column(String(64), primary_key=True)             # = tenant_id
    name = Column(String(200), nullable=False)
    plan = Column(String(32), default="free")
    status = Column(String(32), default="active")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class LongTermMemoryDB(Base):
    """长期记忆（SQLAlchemy 双后端落库：Postgres / SQLite 自动切换）

    与 long_term.py 的 psycopg2 老表 long_term_memory 解耦：
    - PG 模式下 long_term.py 仍走 psycopg2（保持兼容，不双写）
    - 本地 auto / SQLite 模式下走本表，解决长期记忆重启即失问题
    """
    __tablename__ = "long_term_memories"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), default="default", index=True)
    user_id = Column(String(64), default="", index=True)
    topic = Column(String(200), default="")
    content = Column(Text, default="")
    importance = Column(Float, default=0.5)
    metadata_json = Column(Text, default="{}")
    timestamp = Column(DateTime, default=_utcnow)
    status = Column(String(32), default="active")
    access_count = Column(Integer, default=0)
