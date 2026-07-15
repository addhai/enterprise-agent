"""工单管理 MCP 工具集 — create / update / query / list / close / add_comment

设计要点：
    1. 复用 src.agent.tools.PermissionChecker 实现三层鉴权
    2. 工具描述只写"什么时候用"，不写"谁能用"（权限在闭包里做）
    3. 多租户隔离：所有工具自动带上调用者的 tenant_id，LLM 无法跨租户
    4. 所有写操作走 audit_log

权限矩阵：
    ticket_create        → 任何已认证用户（需 user_id）
    ticket_query/list     → 用户查自己的，admin 查任意
    ticket_update/close   → admin 或 assignee
    ticket_add_comment    → 已认证用户
"""
import logging
from typing import Callable, List, Optional

from langchain_core.tools import tool

from src.agent.tools import PermissionChecker
from src.ticket.models import (
    Comment,
    Ticket,
    TicketCategory,
    TicketCreateRequest,
    TicketListFilter,
    TicketPriority,
    TicketStatus,
    TicketUpdateRequest,
)
from src.ticket.store import InMemoryTicketStore, get_default_store

logger = logging.getLogger(__name__)


# 受限工具：只有 admin 或被授权角色可以调用
_TICKET_WRITE_ROLES = {"admin", "support_agent", "billing_manager"}


def _ticket_to_summary(t: Ticket) -> str:
    """格式化工单为易读字符串（MCP 工具返回值）"""
    parts = [
        f"ID: {t.id}",
        f"Title: {t.title}",
        f"Status: {t.status.value}",
        f"Priority: {t.priority.value}",
        f"Category: {t.category.value}",
        f"User: {t.user_id}",
        f"Tenant: {t.tenant_id}",
    ]
    if t.assignee:
        parts.append(f"Assignee: {t.assignee}")
    if t.tags:
        parts.append(f"Tags: {', '.join(t.tags)}")
    if t.description:
        # 截断过长描述
        desc = t.description if len(t.description) <= 200 \
            else t.description[:200] + "..."
        parts.append(f"Description: {desc}")
    if t.comments:
        parts.append(f"Comments: {len(t.comments)} 条")
    parts.append(f"Created: {t.created_at.isoformat()}")
    parts.append(f"Updated: {t.updated_at.isoformat()}")
    return "\n".join(parts)


def create_ticket_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    store: Optional[InMemoryTicketStore] = None,
    authority_source: Optional[Callable] = None,
) -> List:
    """创建工单管理工具列表

    Args:
        user_id: 调用者 user_id
        tenant_id: 调用者 tenant_id（多租户隔离强制）
        roles: 调用者角色列表
        plan: 订阅计划
        store: 工单存储实例，默认用全局内存存储
        authority_source: 权威数据源回调（敏感操作前刷新权限）
    """
    checker = PermissionChecker(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles or [],
        access_levels=["public"],
        plan=plan,
        authority_source=authority_source,
    )
    ticket_store = store or get_default_store()

    @tool
    def ticket_create(
        title: str,
        description: str,
        category: str = "other",
        priority: str = "medium",
        tags: str = "",
        idempotency_key: str = "",
    ) -> str:
        """创建客服工单，记录用户反馈的问题或请求。

        何时使用：用户需要提交工单、跟踪问题处理进度，或 escalate_to_human
        之前需要正式登记问题。比如"我要提交一个退款工单"、"帮我开个工单跟进 SSO 配置"。

        Args:
            title: 工单标题，简洁描述问题（<=200 字符）
            description: 工单详细描述
            category: 分类，可选值: billing/technical/account/sso/api/complaint/other
            priority: 优先级，可选值: low/medium/high/urgent
            tags: 标签，逗号分隔，如 "退款,企业版"
            idempotency_key: 幂等键（可选），相同键重复调用不会创建新工单
        """
        if not checker.check("ticket_create"):
            return "[权限不足] 您没有权限创建工单。"

        try:
            cat = TicketCategory(category)
        except ValueError:
            return f"[参数错误] 无效的 category: {category}，可选: {[c.value for c in TicketCategory]}"
        try:
            prio = TicketPriority(priority)
        except ValueError:
            return f"[参数错误] 无效的 priority: {priority}，可选: {[p.value for p in TicketPriority]}"

        # 参数校验：tenant_id 由后端注入，防止 LLM 越权
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        req = TicketCreateRequest(
            tenant_id=tenant_id,            # 强制用调用者的 tenant_id
            user_id=user_id,               # 强制用调用者的 user_id
            title=title,
            description=description,
            category=cat,
            priority=prio,
            tags=tag_list,
            idempotency_key=idempotency_key or None,
        )
        ticket = ticket_store.create(req)
        logger.info("MCP ticket_create: id=%s by user=%s", ticket.id, user_id)
        return f"[工单已创建]\n{_ticket_to_summary(ticket)}"

    @tool
    def ticket_query(ticket_id: str) -> str:
        """查询单个工单的完整信息（含状态、评论、处理人）。

        何时使用：用户询问某个工单进度、查看工单详情，比如"TKT-ABCD1234 现在什么状态了"。

        Args:
            ticket_id: 工单 ID，格式 TKT-XXXXXXXX
        """
        if not checker.check("ticket_query"):
            return "[权限不足] 您没有权限查询工单。"

        ticket = ticket_store.get(ticket_id, tenant_id)
        if ticket is None:
            return f"[未找到] 工单 {ticket_id} 不存在或不属于当前租户。"

        # 资源级权限：非 admin 只能查自己的工单
        if ticket.user_id != user_id and "admin" not in checker.roles:
            checker._audit(
                "TICKET_ACCESS_DENIED", "ticket_query",
                f"user={user_id} tried to read ticket owned by {ticket.user_id}",
            )
            return "[权限不足] 您只能查看自己提交的工单。"

        return _ticket_to_summary(ticket)

    @tool
    def ticket_list(
        status: str = "",
        category: str = "",
        priority: str = "",
        limit: int = 20,
    ) -> str:
        """列出工单（默认按创建时间倒序）。

        何时使用：用户想看自己有哪些工单、按状态/优先级过滤。比如"列出我所有未解决的工单"。
        普通用户只能看到自己的工单，admin 可看租户内全部。

        Args:
            status: 按状态过滤，可选: open/in_progress/resolved/closed/cancelled
            category: 按分类过滤，可选: billing/technical/account/sso/api/complaint/other
            priority: 按优先级过滤，可选: low/medium/high/urgent
            limit: 返回条数上限，1-100
        """
        if not checker.check("ticket_list"):
            return "[权限不足] 您没有权限列出工单。"

        try:
            f = TicketListFilter(
                tenant_id=tenant_id,
                # admin 可见租户内全部，普通用户仅见自己的
                user_id=None if "admin" in checker.roles else user_id,
                status=TicketStatus(status) if status else None,
                category=TicketCategory(category) if category else None,
                priority=TicketPriority(priority) if priority else None,
                limit=max(1, min(100, limit)),
            )
        except ValueError as e:
            return f"[参数错误] {str(e)}"

        tickets = ticket_store.list(f)
        if not tickets:
            return "[查询完成] 当前没有匹配的工单。"

        lines = [f"[查询完成] 共 {len(tickets)} 条工单:"]
        for t in tickets:
            lines.append(
                f"  • {t.id} | {t.status.value} | {t.priority.value} | "
                f"{t.category.value} | {t.title}"
            )
        return "\n".join(lines)

    @tool
    def ticket_update(
        ticket_id: str,
        status: str = "",
        priority: str = "",
        assignee: str = "",
        category: str = "",
        title: str = "",
        description: str = "",
        tags: str = "",
    ) -> str:
        """更新工单字段（状态/优先级/分配/分类等）。

        何时使用：客服需要改工单状态、重新分配、调整优先级。
        仅 admin 或 support_agent 可调用，普通用户请用 ticket_add_comment 补充信息。

        Args:
            ticket_id: 工单 ID
            status: 新状态，可选: open/in_progress/resolved/closed/cancelled
            priority: 新优先级，可选: low/medium/high/urgent
            assignee: 分配给的客服 ID
            category: 新分类
            title: 新标题
            description: 新描述
            tags: 新标签（逗号分隔，会整体替换）
        """
        if not checker.check("ticket_update"):
            return "[权限不足] 您没有权限更新工单。"

        # 写操作需 admin/support 角色权限
        if not (set(checker.roles) & _TICKET_WRITE_ROLES):
            checker._audit(
                "TICKET_WRITE_DENIED", "ticket_update",
                f"roles={checker.roles} insufficient for write",
            )
            return "[权限不足] 更新工单需要 admin 或 support_agent 角色。"

        # 解析可选枚举
        try:
            update_req = TicketUpdateRequest(
                title=title or None,
                description=description or None,
                category=TicketCategory(category) if category else None,
                priority=TicketPriority(priority) if priority else None,
                status=TicketStatus(status) if status else None,
                assignee=assignee or None,
                tags=[t.strip() for t in tags.split(",") if t.strip()] if tags else None,
            )
        except ValueError as e:
            return f"[参数错误] {str(e)}"

        ticket = ticket_store.update(ticket_id, tenant_id, update_req)
        if ticket is None:
            return f"[更新失败] 工单 {ticket_id} 不存在、已关闭或属于其他租户。"

        logger.info("MCP ticket_update: id=%s by user=%s", ticket_id, user_id)
        return f"[工单已更新]\n{_ticket_to_summary(ticket)}"

    @tool
    def ticket_close(
        ticket_id: str,
        resolution: str,
    ) -> str:
        """关闭工单并记录解决方案。

        何时使用：问题已解决或用户确认取消，需要正式关闭工单。
        仅 admin 或 support_agent 可调用。

        Args:
            ticket_id: 工单 ID
            resolution: 关闭说明/解决方案（必填，会作为最后一条评论保存）
        """
        if not checker.check("ticket_close"):
            return "[权限不足] 您没有权限关闭工单。"

        if not (set(checker.roles) & _TICKET_WRITE_ROLES):
            checker._audit(
                "TICKET_CLOSE_DENIED", "ticket_close",
                f"roles={checker.roles} insufficient",
            )
            return "[权限不足] 关闭工单需要 admin 或 support_agent 角色。"

        if not resolution.strip():
            return "[参数错误] resolution 不能为空。"

        # 1. 先追加一条 resolution 评论
        closing_comment = Comment(
            author=user_id,
            content=f"[Resolution] {resolution}",
        )
        ticket_store.add_comment(ticket_id, tenant_id, closing_comment)

        # 2. 再把状态改为 closed
        update_req = TicketUpdateRequest(status=TicketStatus.CLOSED)
        ticket = ticket_store.update(ticket_id, tenant_id, update_req)
        if ticket is None:
            return f"[关闭失败] 工单 {ticket_id} 不存在、已关闭或属于其他租户。"

        logger.info("MCP ticket_close: id=%s by user=%s", ticket_id, user_id)
        return f"[工单已关闭]\n{_ticket_to_summary(ticket)}"

    @tool
    def ticket_add_comment(
        ticket_id: str,
        content: str,
    ) -> str:
        """给工单追加评论/跟进记录。

        何时使用：用户想补充信息、客服记录处理过程、或转人工前附加上下文。
        普通用户只能评论自己的工单，admin/support 可评论任意本租户工单。

        Args:
            ticket_id: 工单 ID
            content: 评论内容
        """
        if not checker.check("ticket_add_comment"):
            return "[权限不足] 您没有权限添加评论。"

        if not content.strip():
            return "[参数错误] content 不能为空。"

        # 资源级权限检查
        existing = ticket_store.get(ticket_id, tenant_id)
        if existing is None:
            return f"[未找到] 工单 {ticket_id} 不存在或不属于当前租户。"
        if existing.user_id != user_id and "admin" not in checker.roles \
                and "support_agent" not in checker.roles:
            checker._audit(
                "COMMENT_DENIED", "ticket_add_comment",
                f"user={user_id} tried to comment on ticket owned by {existing.user_id}",
            )
            return "[权限不足] 您只能给自己提交的工单评论。"

        comment = Comment(author=user_id, content=content)
        updated = ticket_store.add_comment(ticket_id, tenant_id, comment)
        if updated is None:
            return f"[评论失败] 工单 {ticket_id} 不存在或已关闭。"

        logger.info("MCP ticket_add_comment: id=%s by user=%s", ticket_id, user_id)
        return f"[评论已添加到工单 {ticket_id}] 共 {len(updated.comments)} 条评论。"

    return [
        ticket_create,
        ticket_query,
        ticket_list,
        ticket_update,
        ticket_close,
        ticket_add_comment,
    ]
