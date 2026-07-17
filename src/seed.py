"""演示数据初始化

在应用启动时注入一些模拟数据，方便前端展示和测试。
注意：当前使用内存存储，重启后数据会丢失。
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
            "title": "企业版 API 配额申请",
            "description": "我们需要申请更高的 API 调用配额，当前每月 10 万次不够用。",
            "category": TicketCategory.API,
            "priority": TicketPriority.HIGH,
            "user_id": "user_001",
            "assignee": "admin",
            "status": TicketStatus.IN_PROGRESS,
            "tags": ["企业版", "API"],
        },
        {
            "title": "飞书机器人无法响应",
            "description": "配置完飞书应用后，机器人在群里没有反应，回调地址已确认正确。",
            "category": TicketCategory.TECHNICAL,
            "priority": TicketPriority.URGENT,
            "user_id": "user_002",
            "assignee": "admin",
            "status": TicketStatus.OPEN,
            "tags": ["飞书", "机器人"],
        },
        {
            "title": "知识库文档同步失败",
            "description": "上传 PDF 后解析进度卡在 80%，多次重试无效。",
            "category": TicketCategory.TECHNICAL,
            "priority": TicketPriority.MEDIUM,
            "user_id": "user_003",
            "assignee": None,
            "status": TicketStatus.OPEN,
            "tags": ["知识库", "PDF"],
        },
        {
            "title": "咨询企业版报价",
            "description": "想了解一下 500 人团队使用企业版的年费和部署方式。",
            "category": TicketCategory.BILLING,
            "priority": TicketPriority.LOW,
            "user_id": "user_004",
            "assignee": "admin",
            "status": TicketStatus.RESOLVED,
            "tags": ["报价", "企业版"],
        },
        {
            "title": "SSO 单点登录配置指导",
            "description": "希望对接公司内部的 OIDC 服务，需要配置文档和示例。",
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
    from src.api.satisfaction import _satisfaction_records
    if _satisfaction_records:
        return

    samples = [
        {"session_id": "sess_001", "user_id": "user_001", "score": 5, "tags": ["响应快", "解决问题"], "comment": "非常满意，AI 直接解决了我的问题。", "agent_id": None},
        {"session_id": "sess_002", "user_id": "user_002", "score": 4, "tags": ["专业"], "comment": "人工客服很专业，但等待时间稍长。", "agent_id": "admin"},
        {"session_id": "sess_003", "user_id": "user_003", "score": 3, "tags": ["一般"], "comment": "基本解决了，但流程有点繁琐。", "agent_id": None},
        {"session_id": "sess_004", "user_id": "user_004", "score": 5, "tags": ["耐心", "详细"], "comment": "客服解释得很清楚，已确认采购方案。", "agent_id": "admin"},
        {"session_id": "sess_005", "user_id": "user_005", "score": 2, "tags": ["未解决"], "comment": "问题没有解决，转了好几轮。", "agent_id": None},
    ]

    now = time.time()
    for i, s in enumerate(samples):
        _satisfaction_records.append({
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
        {"user_id": "user_001", "username": "张三", "email": "zhangsan@example.com", "company": "未来科技", "plan": "enterprise", "tags": ["大客户", "API"]},
        {"user_id": "user_002", "username": "李四", "email": "lisi@example.com", "company": "创新工场", "plan": "pro", "tags": ["飞书", "技术支持"]},
        {"user_id": "user_003", "username": "王五", "email": "wangwu@example.com", "company": "智慧教育", "plan": "free", "tags": ["知识库"]},
        {"user_id": "user_004", "username": "赵六", "email": "zhaoliu@example.com", "company": "蓝海集团", "plan": "enterprise", "tags": ["采购咨询"]},
        {"user_id": "user_005", "username": "孙七", "email": "sunqi@example.com", "company": "星辰网络", "plan": "pro", "tags": ["SSO"]},
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
