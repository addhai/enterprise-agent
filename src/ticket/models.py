"""工单数据模型 — Pydantic models，与存储后端解耦

字段设计对齐项目多租户隔离约定（tenant_id 前缀）和 capability-contract.yaml 的幂等要求。
"""
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    """工单状态机：open → in_progress → resolved | closed | cancelled"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TicketPriority(str, Enum):
    """优先级：low / medium / high / urgent"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketCategory(str, Enum):
    """工单分类，对齐客服 Agent 现有技能划分"""
    BILLING = "billing"            # 账单/退款
    TECHNICAL = "technical"        # 技术排障
    ACCOUNT = "account"           # 账号操作
    SSO = "sso"                    # SSO 配置
    API = "api"                    # API/SDK
    COMPLAINT = "complaint"        # 投诉
    OTHER = "other"


class Comment(BaseModel):
    """工单评论/跟进记录"""
    id: str = Field(default_factory=lambda: f"cmt_{uuid4().hex[:12]}")
    author: str
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Ticket(BaseModel):
    """工单主实体"""
    id: str = Field(default_factory=lambda: f"TKT-{uuid4().hex[:8].upper()}")
    tenant_id: str
    user_id: str                       # 提交者 user_id
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: TicketCategory = TicketCategory.OTHER
    priority: TicketPriority = TicketPriority.MEDIUM
    status: TicketStatus = TicketStatus.OPEN
    assignee: Optional[str] = None    # 分配给的客服/团队
    tags: List[str] = Field(default_factory=list)
    comments: List[Comment] = Field(default_factory=list)
    idempotency_key: Optional[str] = None   # 幂等键，防重复创建
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None

    def touch(self):
        self.updated_at = datetime.now(timezone.utc)


class TicketCreateRequest(BaseModel):
    """创建工单的请求"""
    tenant_id: str
    user_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: TicketCategory = TicketCategory.OTHER
    priority: TicketPriority = TicketPriority.MEDIUM
    tags: List[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None


class TicketUpdateRequest(BaseModel):
    """更新工单的请求 — 所有字段可选"""
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[TicketCategory] = None
    priority: Optional[TicketPriority] = None
    status: Optional[TicketStatus] = None
    assignee: Optional[str] = None
    tags: Optional[List[str]] = None


class TicketListFilter(BaseModel):
    """列表查询过滤器"""
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    status: Optional[TicketStatus] = None
    category: Optional[TicketCategory] = None
    priority: Optional[TicketPriority] = None
    assignee: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=10000)
