"""工单存储后端 — 抽象接口 + 内存实现 + PG 适配预留

设计原则：
    1. 定义 TicketStore 抽象基类，存储后端可替换（内存/PG/Redis）
    2. InMemoryTicketStore：开发/测试/MCP 单机部署使用
    3. 幂等保证：相同 idempotency_key 的创建请求返回同一张工单
    4. 多租户隔离：所有读写都按 tenant_id 过滤
    5. 线程安全：内存实现用 threading.Lock 保护

未来扩展：PgTicketStore 可对接 src/config.py 中的 database_url
"""
import logging
import threading
from typing import Dict, List, Optional, Protocol

from src.ticket.models import (
    Comment,
    Ticket,
    TicketCreateRequest,
    TicketListFilter,
    TicketStatus,
    TicketUpdateRequest,
)

logger = logging.getLogger(__name__)


class TicketStore(Protocol):
    """工单存储接口契约"""

    def create(self, req: TicketCreateRequest) -> Ticket:
        ...

    def get(self, ticket_id: str, tenant_id: str) -> Optional[Ticket]:
        ...

    def update(
        self,
        ticket_id: str,
        tenant_id: str,
        req: TicketUpdateRequest,
    ) -> Optional[Ticket]:
        ...

    def list(self, filter: TicketListFilter) -> List[Ticket]:
        ...

    def add_comment(
        self,
        ticket_id: str,
        tenant_id: str,
        comment: Comment,
    ) -> Optional[Ticket]:
        ...

    def delete(self, ticket_id: str, tenant_id: str) -> bool:
        ...


class InMemoryTicketStore:
    """内存工单存储 — 线程安全，适合单机部署和测试

    幂等策略：
        - 创建时如果带 idempotency_key，则查找已有同 key 工单直接返回
        - 与 capability-contract.yaml 的 idempotency.strategy=store-result 对齐
    """

    def __init__(self):
        self._tickets: Dict[str, Ticket] = {}             # ticket_id -> Ticket
        self._idem_index: Dict[str, str] = {}             # idempotency_key -> ticket_id
        self._lock = threading.RLock()

    def create(self, req: TicketCreateRequest) -> Ticket:
        with self._lock:
            # 幂等检查
            if req.idempotency_key:
                existing_id = self._idem_index.get(req.idempotency_key)
                if existing_id and existing_id in self._tickets:
                    logger.info(
                        "Idempotent create: returning existing ticket %s",
                        existing_id,
                    )
                    return self._tickets[existing_id]

            ticket = Ticket(
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                title=req.title,
                description=req.description,
                category=req.category,
                priority=req.priority,
                tags=list(req.tags),
                idempotency_key=req.idempotency_key,
            )
            self._tickets[ticket.id] = ticket
            if req.idempotency_key:
                self._idem_index[req.idempotency_key] = ticket.id

            logger.info(
                "Ticket created: id=%s tenant=%s user=%s title=%s",
                ticket.id, ticket.tenant_id, ticket.user_id, ticket.title,
            )
            return ticket

    def get(self, ticket_id: str, tenant_id: str) -> Optional[Ticket]:
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None or ticket.tenant_id != tenant_id:
                return None
            return ticket

    def update(
        self,
        ticket_id: str,
        tenant_id: str,
        req: TicketUpdateRequest,
    ) -> Optional[Ticket]:
        with self._lock:
            ticket = self.get(ticket_id, tenant_id)
            if ticket is None:
                return None

            # 已关闭工单不允许修改核心字段
            if ticket.status in (TicketStatus.CLOSED, TicketStatus.CANCELLED):
                logger.warning(
                    "Attempt to update closed ticket %s (status=%s)",
                    ticket_id, ticket.status,
                )
                return None

            changes = []
            for field in ("title", "description", "category",
                          "priority", "status", "assignee", "tags"):
                value = getattr(req, field)
                if value is not None:
                    old = getattr(ticket, field)
                    setattr(ticket, field, value)
                    changes.append(f"{field}: {old!r} -> {value!r}")

                    if field == "status" and value in (
                        TicketStatus.CLOSED, TicketStatus.CANCELLED,
                    ):
                        from datetime import datetime, timezone
                        ticket.closed_at = datetime.now(timezone.utc)

            if changes:
                ticket.touch()
                logger.info(
                    "Ticket updated: id=%s changes=[%s]",
                    ticket_id, "; ".join(changes),
                )
            return ticket

    def list(self, filter: TicketListFilter) -> List[Ticket]:
        with self._lock:
            results = []
            for ticket in self._tickets.values():
                if filter.tenant_id and ticket.tenant_id != filter.tenant_id:
                    continue
                if filter.user_id and ticket.user_id != filter.user_id:
                    continue
                if filter.status and ticket.status != filter.status:
                    continue
                if filter.category and ticket.category != filter.category:
                    continue
                if filter.priority and ticket.priority != filter.priority:
                    continue
                if filter.assignee and ticket.assignee != filter.assignee:
                    continue
                results.append(ticket)
            # 按创建时间倒序
            results.sort(key=lambda t: t.created_at, reverse=True)
            return results[:filter.limit]

    def add_comment(
        self,
        ticket_id: str,
        tenant_id: str,
        comment: Comment,
    ) -> Optional[Ticket]:
        with self._lock:
            ticket = self.get(ticket_id, tenant_id)
            if ticket is None:
                return None
            ticket.comments.append(comment)
            ticket.touch()
            logger.info(
                "Comment added: ticket=%s author=%s",
                ticket_id, comment.author,
            )
            return ticket

    def delete(self, ticket_id: str, tenant_id: str) -> bool:
        with self._lock:
            ticket = self.get(ticket_id, tenant_id)
            if ticket is None:
                return False
            del self._tickets[ticket_id]
            if ticket.idempotency_key:
                self._idem_index.pop(ticket.idempotency_key, None)
            logger.info("Ticket deleted: id=%s", ticket_id)
            return True


# ---------------------------------------------------------------------------
# 全局单例（MCP 单机部署使用）
# ---------------------------------------------------------------------------

_global_store: Optional[InMemoryTicketStore] = None
_store_lock = threading.Lock()


def get_default_store() -> InMemoryTicketStore:
    """获取全局内存工单存储单例"""
    global _global_store
    if _global_store is None:
        with _store_lock:
            if _global_store is None:
                _global_store = InMemoryTicketStore()
                logger.info("Initialized global InMemoryTicketStore")
    return _global_store


def reset_default_store() -> None:
    """重置全局存储（仅测试使用）"""
    global _global_store
    with _store_lock:
        _global_store = None
