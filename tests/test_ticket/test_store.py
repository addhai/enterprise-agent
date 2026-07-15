"""工单存储后端测试"""
import pytest

from src.ticket.models import (
    TicketCreateRequest,
    TicketListFilter,
    TicketStatus,
    TicketPriority,
    TicketCategory,
    TicketUpdateRequest,
)
from src.ticket.store import InMemoryTicketStore


@pytest.fixture
def store():
    return InMemoryTicketStore()


@pytest.fixture
def sample_create_req():
    return TicketCreateRequest(
        tenant_id="tenant_A",
        user_id="user_1",
        title="无法登录账号",
        description="点击登录按钮无响应",
        category=TicketCategory.ACCOUNT,
        priority=TicketPriority.HIGH,
        tags=["登录", "紧急"],
    )


def test_create_returns_ticket_with_id(store, sample_create_req):
    """创建工单应返回带 ID 的 Ticket 对象"""
    ticket = store.create(sample_create_req)

    assert ticket.id.startswith("TKT-")
    assert ticket.tenant_id == "tenant_A"
    assert ticket.user_id == "user_1"
    assert ticket.title == "无法登录账号"
    assert ticket.status == TicketStatus.OPEN
    assert ticket.priority == TicketPriority.HIGH
    assert ticket.category == TicketCategory.ACCOUNT
    assert ticket.tags == ["登录", "紧急"]
    # created_at 和 updated_at 由两个 default_factory 独立调用，可能有微秒级差异
    assert ticket.updated_at >= ticket.created_at


def test_create_idempotency(store, sample_create_req):
    """相同 idempotency_key 的创建请求应返回同一张工单"""
    sample_create_req.idempotency_key = "req-abc-001"
    first = store.create(sample_create_req)
    second = store.create(sample_create_req)

    assert first.id == second.id, "幂等创建应返回同一张工单"


def test_get_by_tenant_isolation(store, sample_create_req):
    """不同租户应互相隔离"""
    store.create(sample_create_req)
    sample_create_req.idempotency_key = None
    sample_create_req.title = "另一个工单"
    ticket = store.create(sample_create_req)

    # 同租户可见
    found = store.get(ticket.id, "tenant_A")
    assert found is not None
    assert found.title == "另一个工单"

    # 不同租户不可见
    not_found = store.get(ticket.id, "tenant_B")
    assert not_found is None


def test_update_changes_fields(store, sample_create_req):
    """update 应修改对应字段并更新 updated_at"""
    ticket = store.create(sample_create_req)
    original_updated = ticket.updated_at

    update_req = TicketUpdateRequest(
        status=TicketStatus.IN_PROGRESS,
        assignee="agent_007",
        priority=TicketPriority.URGENT,
    )
    updated = store.update(ticket.id, "tenant_A", update_req)

    assert updated.status == TicketStatus.IN_PROGRESS
    assert updated.assignee == "agent_007"
    assert updated.priority == TicketPriority.URGENT
    assert updated.updated_at >= original_updated


def test_update_closed_ticket_rejected(store, sample_create_req):
    """已关闭工单不允许再修改"""
    ticket = store.create(sample_create_req)
    store.update(
        ticket.id, "tenant_A",
        TicketUpdateRequest(status=TicketStatus.CLOSED),
    )

    result = store.update(
        ticket.id, "tenant_A",
        TicketUpdateRequest(priority=TicketPriority.URGENT),
    )
    assert result is None, "已关闭工单不应允许修改"


def test_update_sets_closed_at(store, sample_create_req):
    """关闭/取消工单时应记录 closed_at"""
    ticket = store.create(sample_create_req)
    assert ticket.closed_at is None

    updated = store.update(
        ticket.id, "tenant_A",
        TicketUpdateRequest(status=TicketStatus.CLOSED),
    )
    assert updated.closed_at is not None


def test_list_filters_by_tenant(store):
    """list 应按租户过滤"""
    store.create(TicketCreateRequest(
        tenant_id="tenant_A", user_id="u1", title="A1",
    ))
    store.create(TicketCreateRequest(
        tenant_id="tenant_A", user_id="u2", title="A2",
    ))
    store.create(TicketCreateRequest(
        tenant_id="tenant_B", user_id="u3", title="B1",
    ))

    a_tickets = store.list(TicketListFilter(tenant_id="tenant_A"))
    b_tickets = store.list(TicketListFilter(tenant_id="tenant_B"))

    assert len(a_tickets) == 2
    assert len(b_tickets) == 1
    assert all(t.tenant_id == "tenant_A" for t in a_tickets)


def test_list_filters_by_status_and_user(store):
    """list 应支持多维度过滤"""
    store.create(TicketCreateRequest(
        tenant_id="t", user_id="u1", title="t1",
    ))
    t2 = store.create(TicketCreateRequest(
        tenant_id="t", user_id="u1", title="t2",
    ))
    store.update(t2.id, "t", TicketUpdateRequest(status=TicketStatus.RESOLVED))

    # 只看 open
    open_tickets = store.list(TicketListFilter(
        tenant_id="t", status=TicketStatus.OPEN,
    ))
    assert len(open_tickets) == 1
    assert open_tickets[0].title == "t1"

    # 只看 u1 的
    user_tickets = store.list(TicketListFilter(tenant_id="t", user_id="u1"))
    assert len(user_tickets) == 2


def test_list_limit_clamped(store):
    """list 应尊重 limit 上限"""
    for i in range(5):
        store.create(TicketCreateRequest(
            tenant_id="t", user_id="u", title=f"t{i}",
        ))

    limited = store.list(TicketListFilter(tenant_id="t", limit=2))
    assert len(limited) == 2


def test_add_comment_appends(store, sample_create_req):
    """add_comment 应追加评论并更新工单时间"""
    from src.ticket.models import Comment

    ticket = store.create(sample_create_req)
    original_updated = ticket.updated_at

    comment = Comment(author="agent_1", content="已联系用户")
    updated = store.add_comment(ticket.id, "tenant_A", comment)

    assert len(updated.comments) == 1
    assert updated.comments[0].author == "agent_1"
    assert updated.comments[0].content == "已联系用户"
    assert updated.updated_at >= original_updated


def test_delete_removes_ticket(store, sample_create_req):
    """delete 应移除工单和幂等索引"""
    sample_create_req.idempotency_key = "key-001"
    ticket = store.create(sample_create_req)

    assert store.delete(ticket.id, "tenant_A") is True
    assert store.get(ticket.id, "tenant_A") is None

    # 删除后幂等键应被清除，再创建相同 key 会生成新工单
    new_ticket = store.create(sample_create_req)
    assert new_ticket.id != ticket.id


def test_delete_cross_tenant_fails(store, sample_create_req):
    """删除其他租户的工单应失败"""
    ticket = store.create(sample_create_req)
    assert store.delete(ticket.id, "tenant_B") is False
    assert store.get(ticket.id, "tenant_A") is not None
