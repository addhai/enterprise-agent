"""演示数据初始化

在应用启动时注入一些模拟数据，方便前端展示和测试。
注意：业务数据现已持久化（Postgres / SQLite），重启后不丢失；
演示数据仅在数据库为空时注入，重复启动不会重复生成。
"""
import time
import logging
from datetime import datetime, timezone, timedelta

from src.ticket.models import (
    TicketCreateRequest, TicketUpdateRequest, TicketListFilter,
    TicketStatus, TicketPriority, TicketCategory
)
from src.ticket.store import get_default_store

logger = logging.getLogger(__name__)


def seed_demo_data():
    """注入演示数据"""
    try:
        _seed_tickets()
        _seed_satisfaction()
        _seed_customers()
        logger.info("Demo data seeded successfully")
    except Exception as e:
        logger.warning("Failed to seed demo data: %s", e)


def _seed_tickets():
    """生成示例工单"""
    store = get_default_store()
    # 如果已经有工单则不重复生成
    existing = store.list(TicketListFilter(tenant_id="default", limit=1))
    if existing:
        return

    samples = [
        {
            "title": "Enterprise API quota request",
            "description": "We need to apply for a higher API call quota; the current 100k/month is insufficient.",
            "category": TicketCategory.API,
            "priority": TicketPriority.HIGH,
            "user_id": "user_001",
            "assignee": "admin",
            "status": TicketStatus.IN_PROGRESS,
            "tags": ["enterprise", "API"],
        },
        {
            "title": "Feishu bot is not responding",
            "description": "After configuring the Feishu app, the bot does not respond in the group; the callback URL has been verified.",
            "category": TicketCategory.TECHNICAL,
            "priority": TicketPriority.URGENT,
            "user_id": "user_002",
            "assignee": "admin",
            "status": TicketStatus.OPEN,
            "tags": ["feishu", "bot"],
        },
        {
            "title": "Knowledge base PDF sync stuck",
            "description": "Uploading a PDF gets stuck at 80% parsing progress; multiple retries did not help.",
            "category": TicketCategory.TECHNICAL,
            "priority": TicketPriority.MEDIUM,
            "user_id": "user_003",
            "assignee": None,
            "status": TicketStatus.OPEN,
            "tags": ["knowledge-base", "PDF"],
        },
        {
            "title": "Enterprise pricing inquiry",
            "description": "Want to understand the annual fee and deployment options for a 500-person enterprise plan.",
            "category": TicketCategory.BILLING,
            "priority": TicketPriority.LOW,
            "user_id": "user_004",
            "assignee": "admin",
            "status": TicketStatus.RESOLVED,
            "tags": ["pricing", "enterprise"],
        },
        {
            "title": "SSO single sign-on configuration guide",
            "description": "Need configuration docs and examples for integrating our internal OIDC service.",
            "category": TicketCategory.SSO,
            "priority": TicketPriority.MEDIUM,
            "user_id": "user_005",
            "assignee": "admin",
            "status": TicketStatus.CLOSED,
            "tags": ["SSO", "OIDC"],
        },
    ]

    for i, s in enumerate(samples):
        t = store.create(TicketCreateRequest(
            tenant_id="default",
            user_id=s["user_id"],
            title=s["title"],
            description=s["description"],
            category=s["category"],
            priority=s["priority"],
            tags=s["tags"],
        ))
        # 修改状态和分配人
        update = TicketUpdateRequest(
            status=s["status"],
            assignee=s["assignee"],
        )
        store.update(t.id, "default", update)


def _seed_satisfaction():
    """生成示例满意度记录"""
    from src.db.repositories import satisfaction_list, satisfaction_create
    if satisfaction_list(limit=1):
        return

    samples = [
        {"session_id": "sess_001", "user_id": "user_001", "score": 5, "tags": ["fast", "resolved"], "comment": "Very satisfied; the AI resolved my issue directly.", "agent_id": None},
        {"session_id": "sess_002", "user_id": "user_002", "score": 4, "tags": ["professional"], "comment": "The human agent was professional, but the wait time was a bit long.", "agent_id": "admin"},
        {"session_id": "sess_003", "user_id": "user_003", "score": 3, "tags": ["average"], "comment": "Basically solved, but the process was a bit cumbersome.", "agent_id": None},
        {"session_id": "sess_004", "user_id": "user_004", "score": 5, "tags": ["patient", "detailed"], "comment": "The agent explained clearly and the purchase plan is confirmed.", "agent_id": "admin"},
        {"session_id": "sess_005", "user_id": "user_005", "score": 2, "tags": ["unresolved"], "comment": "Issue not resolved after several rounds of escalation.", "agent_id": None},
    ]

    now = time.time()
    for i, s in enumerate(samples):
        satisfaction_create({
            "id": f"SAT-SEED-{i+1}",
            "session_id": s["session_id"],
            "user_id": s["user_id"],
            "score": s["score"],
            "tags": s["tags"],
            "comment": s["comment"],
            "agent_id": s["agent_id"],
            "created_at": now - i * 3600 * 6,
        })


def _seed_customers():
    """生成示例客户"""
    from src.api.customers import _ensure_customer
    samples = [
        {"user_id": "user_001", "username": "Zhang San", "email": "zhangsan@example.com", "company": "Future Tech", "plan": "enterprise", "tags": ["key-account", "API"]},
        {"user_id": "user_002", "username": "Li Si", "email": "lisi@example.com", "company": "Innovation Works", "plan": "pro", "tags": ["feishu", "tech-support"]},
        {"user_id": "user_003", "username": "Wang Wu", "email": "wangwu@example.com", "company": "Smart Education", "plan": "free", "tags": ["knowledge-base"]},
        {"user_id": "user_004", "username": "Zhao Liu", "email": "zhaoliu@example.com", "company": "Blue Ocean Group", "plan": "enterprise", "tags": ["purchase-inquiry"]},
        {"user_id": "user_005", "username": "Sun Qi", "email": "sunqi@example.com", "company": "Star Network", "plan": "pro", "tags": ["SSO"]},
    ]

    now = time.time()
    for s in samples:
        c = _ensure_customer(s["user_id"], s["username"])
        c.update({
            "email": s["email"],
            "company": s["company"],
            "plan": s["plan"],
            "tags": s["tags"],
            "last_seen_at": now - (hash(s["user_id"]) % 86400),
        })
