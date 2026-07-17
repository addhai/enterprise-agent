"""工单管理 REST API — 完整工单生命周期

基于 src.ticket 模块的内存存储，提供工单列表、详情、创建、更新、分配、评论、关闭能力。
"""
import os
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Query, Body
from pydantic import BaseModel, Field

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.ticket.models import (
    Ticket,
    TicketCreateRequest,
    TicketUpdateRequest,
    TicketListFilter,
    TicketStatus,
    TicketPriority,
    TicketCategory,
    Comment,
)
from src.ticket.store import get_default_store
from src.api.rbac import require_roles, Role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tickets"])


# ====================================================================
# Pydantic 模型
# ====================================================================

class CreateTicketRequest(BaseModel):
    """创建工单请求"""
    tenant_id: str = Field(default="default", description="租户ID")
    user_id: str = Field(..., description="关联客户ID")
    title: str = Field(..., min_length=1, max_length=200, description="工单标题")
    description: str = Field(default="", description="工单描述")
    category: TicketCategory = Field(default=TicketCategory.OTHER, description="工单分类")
    priority: TicketPriority = Field(default=TicketPriority.MEDIUM, description="优先级")
    tags: List[str] = Field(default_factory=list, description="标签")


class AddCommentRequest(BaseModel):
    """添加工单评论请求"""
    content: str = Field(..., min_length=1, max_length=2000, description="评论内容")


class TicketStats(BaseModel):
    """工单统计"""
    total: int = 0
    open: int = 0
    in_progress: int = 0
    resolved: int = 0
    closed: int = 0
    cancelled: int = 0
    urgent: int = 0
    high: int = 0
    unassigned: int = 0
    avg_resolution_minutes: Optional[float] = None


# ====================================================================
# API 路由
# ====================================================================

@router.get("/tickets")
async def list_tickets(
    status: Optional[TicketStatus] = Query(None, description="状态筛选"),
    category: Optional[TicketCategory] = Query(None, description="分类筛选"),
    priority: Optional[TicketPriority] = Query(None, description="优先级筛选"),
    assignee: Optional[str] = Query(None, description="处理人筛选"),
    user_id: Optional[str] = Query(None, description="客户ID筛选"),
    search: Optional[str] = Query(None, description="标题/描述搜索"),
    limit: int = Query(50, ge=1, le=200),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取工单列表"""
    store = get_default_store()
    filter_params = {
        "tenant_id": "default",
        "status": status,
        "category": category,
        "priority": priority,
        "assignee": assignee,
        "user_id": user_id,
        "limit": 1000,
    }
    tickets = store.list(TicketListFilter(**filter_params))

    # agent 角色只能看自己分配的工单
    role = current_user.get("role", "viewer")
    if role == "agent":
        agent_name = current_user.get("username")
        tickets = [t for t in tickets if t.assignee == agent_name or t.assignee is None]

    if search:
        s = search.lower()
        tickets = [
            t for t in tickets
            if s in t.title.lower() or s in t.description.lower()
            or s in t.user_id.lower()
        ]

    tickets.sort(key=lambda t: t.created_at, reverse=True)

    return {
        "total": len(tickets),
        "tickets": [t.dict() for t in tickets[:limit]],
    }


@router.get("/tickets/stats")
async def get_ticket_stats(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取工单统计"""
    store = get_default_store()
    all_tickets = store.list(TicketListFilter(tenant_id="default", limit=10000))

    # agent 只看自己的
    role = current_user.get("role", "viewer")
    if role == "agent":
        agent_name = current_user.get("username")
        all_tickets = [t for t in all_tickets if t.assignee == agent_name or t.assignee is None]

    stats = TicketStats(total=len(all_tickets))
    resolution_times = []

    for t in all_tickets:
        status_key = t.status.value
        if hasattr(stats, status_key):
            setattr(stats, status_key, getattr(stats, status_key) + 1)
        if t.priority in (TicketPriority.URGENT,):
            stats.urgent += 1
        if t.priority in (TicketPriority.HIGH,):
            stats.high += 1
        if not t.assignee:
            stats.unassigned += 1
        if t.closed_at and t.created_at:
            resolution_times.append((t.closed_at - t.created_at).total_seconds() / 60)

    if resolution_times:
        stats.avg_resolution_minutes = round(sum(resolution_times) / len(resolution_times), 2)

    return stats.dict()


@router.get("/tickets/{ticket_id}")
async def get_ticket_detail(
    ticket_id: str,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取工单详情"""
    store = get_default_store()
    ticket = store.get(ticket_id, tenant_id="default")
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    return ticket.dict()


@router.post("/tickets")
async def create_ticket(
    request: CreateTicketRequest,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """创建工单"""
    store = get_default_store()
    req = TicketCreateRequest(
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        title=request.title,
        description=request.description,
        category=request.category,
        priority=request.priority,
        tags=request.tags,
    )
    ticket = store.create(req)

    # 触发通知
    try:
        from src.api.notifications import add_notification
        add_notification(
            type="ticket",
            level="warning",
            title="新工单创建",
            message=f"工单 {ticket.id} 已创建：{ticket.title}",
            target_roles=["super_admin", "admin"],
            link=f"/tickets/{ticket.id}",
        )
    except Exception as e:
        logger.warning("Failed to send ticket notification: %s", e)

    return {"success": True, "ticket": ticket.dict()}


@router.put("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: str,
    request: TicketUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """更新工单"""
    store = get_default_store()

    # agent 不能重新分配或关闭不是自己负责的工单
    existing = store.get(ticket_id, tenant_id="default")
    if not existing:
        raise HTTPException(status_code=404, detail="工单不存在")

    role = current_user.get("role", "viewer")
    if role == "agent":
        agent_name = current_user.get("username")
        if existing.assignee and existing.assignee != agent_name:
            raise HTTPException(status_code=403, detail="无权操作非自己负责的工单")
        # agent 不能提升状态到 closed，只能到 resolved
        if request.status == TicketStatus.CLOSED:
            raise HTTPException(status_code=403, detail="客服无法直接关闭工单")

    ticket = store.update(ticket_id, tenant_id="default", req=request)
    if not ticket:
        raise HTTPException(status_code=400, detail="工单更新失败，可能已关闭")

    return {"success": True, "ticket": ticket.dict()}


@router.post("/tickets/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: str,
    assignee: str = Body(..., embed=True, description="分配对象用户名"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """分配工单"""
    store = get_default_store()
    ticket = store.update(
        ticket_id,
        tenant_id="default",
        req=TicketUpdateRequest(assignee=assignee, status=TicketStatus.IN_PROGRESS),
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或已关闭")

    # 触发通知
    try:
        from src.api.notifications import add_notification
        add_notification(
            type="ticket",
            level="info",
            title="工单已分配",
            message=f"工单 {ticket.id} 已分配给 {assignee}",
            target_users=[assignee],
            link=f"/tickets/{ticket.id}",
        )
    except Exception as e:
        logger.warning("Failed to send assign notification: %s", e)

    return {"success": True, "ticket": ticket.dict()}


@router.post("/tickets/{ticket_id}/comments")
async def add_ticket_comment(
    ticket_id: str,
    request: AddCommentRequest,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """添加工单评论"""
    store = get_default_store()
    existing = store.get(ticket_id, tenant_id="default")
    if not existing:
        raise HTTPException(status_code=404, detail="工单不存在")

    role = current_user.get("role", "viewer")
    if role == "agent":
        agent_name = current_user.get("username")
        if existing.assignee and existing.assignee != agent_name:
            raise HTTPException(status_code=403, detail="无权评论非自己负责的工单")

    comment = Comment(
        author=current_user.get("username", "system"),
        content=request.content,
    )
    ticket = store.add_comment(ticket_id, tenant_id="default", comment=comment)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    return {"success": True, "ticket": ticket.dict()}


@router.post("/tickets/{ticket_id}/close")
async def close_ticket(
    ticket_id: str,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """关闭工单"""
    store = get_default_store()
    ticket = store.update(
        ticket_id,
        tenant_id="default",
        req=TicketUpdateRequest(status=TicketStatus.CLOSED),
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在或已关闭")
    return {"success": True, "ticket": ticket.dict()}


@router.delete("/tickets/{ticket_id}")
async def delete_ticket(
    ticket_id: str,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """删除工单（管理员权限）"""
    store = get_default_store()
    success = store.delete(ticket_id, tenant_id="default")
    if not success:
        raise HTTPException(status_code=404, detail="工单不存在")
    return {"success": True}
