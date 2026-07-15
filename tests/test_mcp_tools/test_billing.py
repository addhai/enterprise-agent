"""账单与订阅 MCP 工具测试 — 权限、CRUD、套餐变更、退款、扣款"""
import pytest

from src.mcp_tools.billing import (
    create_billing_tools,
    _billing_store,
    _transaction_store,
    _refund_store,
)


@pytest.fixture(autouse=True)
def reset_stores():
    """每个测试前清空所有存储"""
    _billing_store._store.clear()
    _billing_store._timestamps.clear()
    _transaction_store._store.clear()
    _transaction_store._timestamps.clear()
    _refund_store._store.clear()
    _refund_store._timestamps.clear()
    yield
    _billing_store._store.clear()
    _transaction_store._store.clear()
    _refund_store._store.clear()


@pytest.fixture
def admin_tools():
    return create_billing_tools(
        user_id="admin_1",
        tenant_id="tenant_A",
        roles=["admin"],
    )


@pytest.fixture
def user_tools():
    return create_billing_tools(
        user_id="user_1",
        tenant_id="tenant_A",
        roles=[],
    )


def _find(tools, name):
    return [t for t in tools if t.name == name][0]


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------

def test_billing_tools_registered(admin_tools):
    """应注册 5 个账单工具"""
    names = {t.name for t in admin_tools}
    expected = {
        "billing_query_subscription",
        "billing_change_plan",
        "billing_refund",
        "billing_list_transactions",
        "billing_deduct",
    }
    assert expected.issubset(names), f"缺少: {expected - names}"


# ---------------------------------------------------------------------------
# billing_query_subscription
# ---------------------------------------------------------------------------

def test_query_subscription_not_found(user_tools):
    """无订阅信息时返回未找到"""
    result = _find(user_tools, "billing_query_subscription").invoke({})
    assert "[未找到]" in result


def test_query_subscription_after_change_plan(admin_tools):
    """变更套餐后应能查到订阅"""
    _find(admin_tools, "billing_change_plan").invoke({"new_plan": "pro"})
    result = _find(admin_tools, "billing_query_subscription").invoke({})
    assert "[查询成功]" in result
    assert "pro" in result


# ---------------------------------------------------------------------------
# billing_change_plan
# ---------------------------------------------------------------------------

def test_change_plan_admin_success(admin_tools):
    """admin 可变更套餐"""
    result = _find(admin_tools, "billing_change_plan").invoke({"new_plan": "pro"})
    assert "[计划已变更]" in result
    assert "pro" in result
    assert "15 CNY" in result


def test_change_plan_user_denied(user_tools):
    """普通用户不能变更套餐"""
    result = _find(user_tools, "billing_change_plan").invoke({"new_plan": "pro"})
    assert "[权限不足]" in result


def test_change_plan_invalid_plan(admin_tools):
    """无效计划名应被拒绝"""
    result = _find(admin_tools, "billing_change_plan").invoke({"new_plan": "platinum"})
    assert "[参数错误]" in result


def test_change_plan_enterprise_price(admin_tools):
    """企业版价格应为 50 CNY"""
    result = _find(admin_tools, "billing_change_plan").invoke({"new_plan": "enterprise"})
    assert "50 CNY" in result


# ---------------------------------------------------------------------------
# billing_refund
# ---------------------------------------------------------------------------

def test_refund_admin_success(admin_tools):
    """admin 可发起退款"""
    result = _find(admin_tools, "billing_refund").invoke({
        "transaction_id": "TRX-001",
        "amount": 99.5,
        "reason": "用户投诉",
    })
    assert "[退款申请已提交]" in result
    assert "99.5 CNY" in result


def test_refund_user_denied(user_tools):
    """普通用户不能退款"""
    result = _find(user_tools, "billing_refund").invoke({
        "transaction_id": "TRX-001",
        "amount": 99.5,
        "reason": "test",
    })
    assert "[权限不足]" in result


def test_refund_zero_amount_rejected(admin_tools):
    """退款金额必须大于 0"""
    result = _find(admin_tools, "billing_refund").invoke({
        "transaction_id": "TRX-001",
        "amount": 0,
        "reason": "test",
    })
    assert "[参数错误]" in result


def test_refund_negative_amount_rejected(admin_tools):
    """负数退款金额被拒绝"""
    result = _find(admin_tools, "billing_refund").invoke({
        "transaction_id": "TRX-001",
        "amount": -10,
        "reason": "test",
    })
    assert "[参数错误]" in result


# ---------------------------------------------------------------------------
# billing_deduct
# ---------------------------------------------------------------------------

def test_deduct_admin_success(admin_tools):
    """admin 可执行扣款"""
    result = _find(admin_tools, "billing_deduct").invoke({
        "amount": 30.0,
        "description": "月度订阅",
    })
    assert "[扣款成功]" in result
    assert "30.0 CNY" in result
    assert "月度订阅" in result


def test_deduct_user_denied(user_tools):
    """普通用户不能扣款"""
    result = _find(user_tools, "billing_deduct").invoke({
        "amount": 10.0,
        "description": "test",
    })
    assert "[权限不足]" in result


def test_deduct_negative_rejected(admin_tools):
    """负数扣款被拒绝"""
    result = _find(admin_tools, "billing_deduct").invoke({
        "amount": -5,
        "description": "test",
    })
    assert "[参数错误]" in result


# ---------------------------------------------------------------------------
# billing_list_transactions
# ---------------------------------------------------------------------------

def test_list_transactions_empty(user_tools):
    """无交易记录时返回空"""
    result = _find(user_tools, "billing_list_transactions").invoke({"limit": 10})
    assert "[查询完成]" in result
    assert "暂无交易记录" in result


def test_list_transactions_after_deduct(admin_tools):
    """扣款后应能在列表中看到"""
    _find(admin_tools, "billing_deduct").invoke({
        "amount": 50.0,
        "description": "测试扣款",
    })
    result = _find(admin_tools, "billing_list_transactions").invoke({"limit": 10})
    assert "共 1 条交易记录" in result
    assert "50.0 CNY" in result
