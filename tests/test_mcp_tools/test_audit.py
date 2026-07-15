"""审计日志 MCP 工具测试 — 查询/导出/按用户搜索/详情"""
import pytest

from src.mcp_tools.audit import (
    create_audit_tools,
    _audit_store,
    record_audit_log,
    AuditLog,
    AuditAction,
)
from src.mcp_tools.common import current_utc_time, generate_id


@pytest.fixture(autouse=True)
def reset_store():
    _audit_store._store.clear()
    _audit_store._timestamps.clear()
    yield
    _audit_store._store.clear()
    _audit_store._timestamps.clear()


@pytest.fixture
def admin_tools():
    return create_audit_tools(
        user_id="admin_1",
        tenant_id="tenant_A",
        roles=["admin"],
    )


@pytest.fixture
def user_tools():
    return create_audit_tools(
        user_id="user_1",
        tenant_id="tenant_A",
        roles=[],
    )


@pytest.fixture
def seeded_logs():
    """预置审计日志"""
    for i in range(5):
        record_audit_log(
            tenant_id="tenant_A",
            user_id="user_42",
            action="login",
            resource=f"resource_{i}",
        )
    record_audit_log(
        tenant_id="tenant_A",
        user_id="admin_1",
        action="create",
        resource="ticket_001",
    )


def _find(tools, name):
    return [t for t in tools if t.name == name][0]


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------

def test_audit_tools_registered(admin_tools):
    names = {t.name for t in admin_tools}
    expected = {
        "audit_query_logs",
        "audit_export_report",
        "audit_search_by_user",
        "audit_get_log_details",
    }
    assert expected.issubset(names)


# ---------------------------------------------------------------------------
# audit_query_logs
# ---------------------------------------------------------------------------

def test_query_logs_admin_success(admin_tools, seeded_logs):
    """admin 可以查询日志"""
    result = _find(admin_tools, "audit_query_logs").invoke({"limit": 10})
    assert "共 6 条日志" in result


def test_query_logs_user_denied(user_tools, seeded_logs):
    """普通用户不能查询"""
    result = _find(user_tools, "audit_query_logs").invoke({"limit": 10})
    assert "[权限不足]" in result


def test_query_logs_empty(admin_tools):
    """无日志时返回空"""
    result = _find(admin_tools, "audit_query_logs").invoke({"limit": 10})
    assert "暂无匹配" in result


def test_query_logs_filter_by_action(admin_tools, seeded_logs):
    """按操作类型过滤"""
    result = _find(admin_tools, "audit_query_logs").invoke({
        "action": "login",
        "limit": 10,
    })
    assert "共 5 条日志" in result


# ---------------------------------------------------------------------------
# audit_search_by_user
# ---------------------------------------------------------------------------

def test_search_by_user_success(admin_tools, seeded_logs):
    """按用户搜索日志"""
    result = _find(admin_tools, "audit_search_by_user").invoke({
        "target_user_id": "user_42",
        "limit": 10,
    })
    assert "共 5 条操作记录" in result


def test_search_by_user_no_records(admin_tools):
    """无记录的用户"""
    result = _find(admin_tools, "audit_search_by_user").invoke({
        "target_user_id": "ghost",
    })
    assert "暂无审计日志" in result


def test_search_by_user_denied(user_tools, seeded_logs):
    """普通用户不能按用户搜索"""
    result = _find(user_tools, "audit_search_by_user").invoke({
        "target_user_id": "user_42",
    })
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# audit_get_log_details
# ---------------------------------------------------------------------------

def test_get_log_details_success(admin_tools, seeded_logs):
    """获取日志详情"""
    logs = _audit_store.list("tenant_A", 10)
    log_id = logs[0].id

    result = _find(admin_tools, "audit_get_log_details").invoke({"log_id": log_id})
    assert "[查询成功]" in result
    assert log_id in result


def test_get_log_details_nonexistent(admin_tools):
    """获取不存在的日志"""
    result = _find(admin_tools, "audit_get_log_details").invoke({"log_id": "AUD-GHOST"})
    assert "[未找到]" in result


def test_get_log_details_user_denied(user_tools, seeded_logs):
    """普通用户不能查看详情"""
    result = _find(user_tools, "audit_get_log_details").invoke({"log_id": "AUD-X"})
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# audit_export_report
# ---------------------------------------------------------------------------

def test_export_report_success(admin_tools, seeded_logs):
    """导出审计报告"""
    result = _find(admin_tools, "audit_export_report").invoke({
        "format": "json",
    })
    assert "[报告已导出]" in result
    assert "total_records: 6" in result
    assert "json" in result


def test_export_report_csv_format(admin_tools, seeded_logs):
    """支持 CSV 格式"""
    result = _find(admin_tools, "audit_export_report").invoke({
        "format": "csv",
    })
    assert "[报告已导出]" in result
    assert "csv" in result


def test_export_report_with_date_range(admin_tools, seeded_logs):
    """支持日期范围"""
    result = _find(admin_tools, "audit_export_report").invoke({
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
    })
    assert "[报告已导出]" in result


def test_export_report_user_denied(user_tools, seeded_logs):
    """普通用户不能导出"""
    result = _find(user_tools, "audit_export_report").invoke({})
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# record_audit_log 内部函数
# ---------------------------------------------------------------------------

def test_record_audit_log_saves():
    """record_audit_log 应保存到存储"""
    initial_count = _audit_store.count("tenant_A")
    record_audit_log(
        tenant_id="tenant_A",
        user_id="test_user",
        action="login",
        resource="test_resource",
        details={"ip": "1.2.3.4"},
    )
    assert _audit_store.count("tenant_A") == initial_count + 1


def test_record_audit_log_with_invalid_action():
    """无效 action 应抛出 ValueError"""
    with pytest.raises(ValueError):
        record_audit_log(
            tenant_id="tenant_A",
            user_id="test_user",
            action="invalid_action_xyz",
            resource="test",
        )


# ---------------------------------------------------------------------------
# 多租户隔离
# ---------------------------------------------------------------------------

def test_cross_tenant_isolation(admin_tools, seeded_logs):
    """不同租户的日志互不可见"""
    b_tools = create_audit_tools(
        user_id="admin_B", tenant_id="tenant_B", roles=["admin"],
    )
    result = _find(b_tools, "audit_query_logs").invoke({"limit": 10})
    assert "暂无匹配" in result
