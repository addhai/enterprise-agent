"""账单与订阅 MCP 工具 — 对接 capability-contract.yaml 中的支付扣款能力"""
import logging
from enum import Enum
from typing import Callable, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agent.tools import PermissionChecker
from src.mcp_tools.common import (
    TenantIsolatedStore,
    current_utc_time,
    format_result,
    generate_id,
    require_admin_or_manager,
)
from src.mcp_tools.audit import record_audit_log

logger = logging.getLogger(__name__)



class SubscriptionPlan(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class BillingStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class Subscription(BaseModel):
    id: str
    tenant_id: str
    plan: SubscriptionPlan
    status: BillingStatus
    start_date: str
    end_date: Optional[str] = None
    monthly_cost: int
    next_billing_date: str
    payment_method: Optional[str] = None


class BillingHistory(BaseModel):
    id: str
    tenant_id: str
    amount: float
    currency: str = "CNY"
    transaction_id: str
    status: str
    description: str
    created_at: str


class RefundRequest(BaseModel):
    id: str
    tenant_id: str
    transaction_id: str
    amount: float
    reason: str
    status: str
    created_at: str


_billing_store = TenantIsolatedStore(max_items_per_tenant=100, name="billing")
_transaction_store = TenantIsolatedStore(max_items_per_tenant=10000, ttl_hours=720, name="transactions")
_refund_store = TenantIsolatedStore(max_items_per_tenant=1000, ttl_hours=168, name="refunds")


def create_billing_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建账单与订阅管理工具"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    @tool
    def billing_query_subscription() -> str:
        """查询当前租户的订阅信息（计划、状态、到期时间、费用）。

        何时使用：用户想知道自己的套餐类型、到期时间、费用等。

        Args:
            无（自动使用当前租户上下文）
        """
        if not checker.check("billing_query_subscription"):
            return format_result("权限不足", "您没有权限查询订阅信息")

        sub = _billing_store.get(tenant_id, tenant_id)
        if sub is None:
            return format_result("未找到", "未查询到订阅信息")

        return format_result("查询成功", "", {
            "plan": sub.plan,
            "status": sub.status,
            "start_date": sub.start_date,
            "end_date": sub.end_date or "永久",
            "monthly_cost": f"{sub.monthly_cost} CNY",
            "next_billing": sub.next_billing_date,
        })

    @tool
    def billing_change_plan(new_plan: str) -> str:
        """变更订阅计划（仅 admin/billing_manager 可调用）。

        何时使用：客服需要帮用户升级/降级套餐。

        Args:
            new_plan: 新计划，可选: free/pro/enterprise
        """
        if not checker.check("billing_change_plan"):
            return format_result("权限不足", "您没有权限变更计划")
        if not require_admin_or_manager(checker, "billing_change_plan"):
            return format_result("权限不足", "需要 admin 或 billing_manager 角色")

        try:
            plan_enum = SubscriptionPlan(new_plan.lower())
        except ValueError:
            return format_result("参数错误", f"无效计划: {new_plan}，可选: free/pro/enterprise")

        # 读取现有订阅，确定当前计划
        existing_sub = _billing_store.get(tenant_id, tenant_id)
        current_plan = existing_sub.plan.value if existing_sub else "free"

        allowed_upgrades = {
            "free": ["pro", "enterprise"],  # free 可升级到 pro 或 enterprise
            "pro": ["enterprise"],
            "enterprise": [],
        }
        if plan_enum.value not in allowed_upgrades.get(current_plan, []):
            if plan_enum.value == current_plan:
                return format_result("无变更", f"当前已是 {current_plan} 计划")
            return format_result(
                "参数越权",
                f"当前计划 {current_plan} 不允许直接变更到 {new_plan}",
            )

        sub = existing_sub
        if sub is None:
            sub = Subscription(
                id=generate_id("SUB"),
                tenant_id=tenant_id,
                plan=plan_enum,
                status=BillingStatus.ACTIVE,
                start_date=current_utc_time().isoformat(),
                monthly_cost={"free": 0, "pro": 15, "enterprise": 50}[new_plan.lower()],
                next_billing_date=current_utc_time().isoformat(),
            )
        else:
            sub.plan = plan_enum
            sub.monthly_cost = {"free": 0, "pro": 15, "enterprise": 50}[new_plan.lower()]
            sub.next_billing_date = current_utc_time().isoformat()

        _billing_store.save(tenant_id, tenant_id, sub)
        logger.info("Subscription changed: tenant=%s plan=%s", tenant_id, new_plan)
        record_audit_log(
            tenant_id=tenant_id,
            user_id=user_id,
            action="update",
            resource=f"subscription:{tenant_id}",
            details={"new_plan": sub.plan, "monthly_cost": sub.monthly_cost},
        )
        return format_result("计划已变更", "", {"plan": sub.plan, "monthly_cost": f"{sub.monthly_cost} CNY"})

    @tool
    def billing_refund(transaction_id: str, amount: float, reason: str) -> str:
        """发起退款申请（仅 admin/billing_manager 可调用）。

        何时使用：客服需要处理用户退款请求。

        Args:
            transaction_id: 交易 ID
            amount: 退款金额
            reason: 退款原因
        """
        if not checker.check("billing_refund"):
            return format_result("权限不足", "您没有权限发起退款")
        if not require_admin_or_manager(checker, "billing_refund"):
            return format_result("权限不足", "需要 admin 或 billing_manager 角色")

        if amount <= 0:
            return format_result("参数错误", "退款金额必须大于 0")

        refund = RefundRequest(
            id=generate_id("RFD"),
            tenant_id=tenant_id,
            transaction_id=transaction_id,
            amount=amount,
            reason=reason,
            status="pending",
            created_at=current_utc_time().isoformat(),
        )
        _refund_store.save(tenant_id, refund.id, refund)

        logger.info("Refund requested: id=%s amount=%.2f", refund.id, amount)
        record_audit_log(
            tenant_id=tenant_id,
            user_id=user_id,
            action="refund",
            resource=f"transaction:{transaction_id}",
            details={"refund_id": refund.id, "amount": amount, "reason": reason},
        )
        return format_result("退款申请已提交", "", {
            "refund_id": refund.id,
            "amount": f"{amount} CNY",
            "status": "待审核",
        })

    @tool
    def billing_list_transactions(limit: int = 20) -> str:
        """列出账单交易记录（按时间倒序）。

        何时使用：用户或客服需要查看消费历史。

        Args:
            limit: 返回条数，默认 20
        """
        if not checker.check("billing_list_transactions"):
            return format_result("权限不足", "您没有权限查看交易记录")

        txns = _transaction_store.list(tenant_id, min(100, max(1, limit)))
        if not txns:
            return format_result("查询完成", "暂无交易记录")

        lines = [f"[查询完成] 共 {len(txns)} 条交易记录:"]
        for t in txns:
            lines.append(f"  • {t.id} | {t.status} | {t.amount} CNY | {t.description}")
        return "\n".join(lines)

    @tool
    def billing_deduct(amount: float, description: str, idempotency_key: str = "") -> str:
        """执行扣款（仅 admin/billing_manager，对接 capability-contract.yaml）。

        何时使用：客服需要对用户账户进行扣款操作。

        Args:
            amount: 扣款金额
            description: 扣款原因
            idempotency_key: 幂等键（可选）
        """
        if not checker.check("billing_deduct"):
            return format_result("权限不足", "您没有权限执行扣款")
        if not require_admin_or_manager(checker, "billing_deduct"):
            return format_result("权限不足", "需要 admin 或 billing_manager 角色")

        if amount <= 0:
            return format_result("参数错误", "扣款金额必须大于 0")

        txn = BillingHistory(
            id=generate_id("TXN"),
            tenant_id=tenant_id,
            amount=amount,
            transaction_id=generate_id("TRX"),
            status="success",
            description=description,
            created_at=current_utc_time().isoformat(),
        )
        _transaction_store.save(tenant_id, txn.id, txn)

        logger.info("Billing deduct: tenant=%s amount=%.2f", tenant_id, amount)
        return format_result("扣款成功", "", {
            "transaction_id": txn.transaction_id,
            "amount": f"{amount} CNY",
            "description": description,
        })

    return [
        billing_query_subscription,
        billing_change_plan,
        billing_refund,
        billing_list_transactions,
        billing_deduct,
    ]
