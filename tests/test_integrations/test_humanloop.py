"""HumanLoopManager 单元测试

覆盖：
- request_approval（启用/未启用）
- submit_review（批准/拒绝/重复审批）
- get_request / list_pending
- is_sensitive_action
- 单例 get_humanloop_manager
"""
import time

import pytest

from src.integrations.humanloop import (
    ApprovalRequest,
    ApprovalResult,
    ApprovalStatus,
    HumanLoopManager,
    SENSITIVE_ACTIONS,
    get_humanloop_manager,
    is_sensitive_action,
)


@pytest.fixture
def manager():
    """启用的 HumanLoopManager"""
    return HumanLoopManager(enabled=True, timeout=5)


@pytest.fixture
def disabled_manager():
    """未启用的 HumanLoopManager"""
    return HumanLoopManager(enabled=False)


# ============================================================
# is_sensitive_action
# ============================================================

class TestIsSensitiveAction:
    def test_known_sensitive_actions(self):
        assert is_sensitive_action("refund") is True
        assert is_sensitive_action("delete_account") is True
        assert is_sensitive_action("export_data") is True
        assert is_sensitive_action("modify_order") is True
        assert is_sensitive_action("large_refund") is True
        assert is_sensitive_action("reset_password") is True
        assert is_sensitive_action("change_permission") is True

    def test_unknown_actions_not_sensitive(self):
        assert is_sensitive_action("faq_query") is False
        assert is_sensitive_action("chat") is False
        assert is_sensitive_action("") is False


# ============================================================
# ApprovalStatus
# ============================================================

class TestApprovalStatus:
    def test_status_values(self):
        assert ApprovalStatus.PENDING == "pending"
        assert ApprovalStatus.APPROVED == "approved"
        assert ApprovalStatus.REJECTED == "rejected"
        assert ApprovalStatus.TIMEOUT == "timeout"
        assert ApprovalStatus.ERROR == "error"


# ============================================================
# 未启用模式
# ============================================================

class TestDisabledManager:
    def test_request_approval_auto_approves(self, disabled_manager):
        result = disabled_manager.request_approval(
            action="refund",
            description="退款 100 元",
            user_id="user-1",
        )
        assert result.approved is True
        assert result.status == ApprovalStatus.APPROVED
        assert result.request_id == ""
        assert "自动放行" in result.message

    def test_list_pending_always_empty(self, disabled_manager):
        assert disabled_manager.list_pending() == []


# ============================================================
# 审批请求创建
# ============================================================

class TestRequestApproval:
    def test_request_creates_pending_request(self, manager):
        # 在另一个线程提交审批
        import threading

        def submit_review_later():
            time.sleep(0.5)
            manager.submit_review(
                request_id=list(manager._requests.keys())[0],
                approved=True,
                reviewer_id="admin",
            )

        thread = threading.Thread(target=submit_review_later)
        thread.start()

        result = manager.request_approval(
            action="refund",
            description="退款 100 元",
            context={"amount": 100, "order_id": "ORD-001"},
            user_id="user-1",
            session_id="session-1",
        )
        thread.join(timeout=3)

        assert result.approved is True
        assert result.status == ApprovalStatus.APPROVED
        assert result.request_id != ""
        assert "通过" in result.message

    def test_request_stores_request(self, manager):
        """即使审批未完成，请求应已存储"""
        import threading

        request_id_holder = {}

        def capture_and_approve():
            time.sleep(0.3)
            rid = list(manager._requests.keys())[0]
            request_id_holder["id"] = rid
            manager.submit_review(rid, approved=True, reviewer_id="admin")

        thread = threading.Thread(target=capture_and_approve)
        thread.start()

        manager.request_approval(
            action="delete_account",
            description="账户注销",
            user_id="user-2",
        )
        thread.join(timeout=3)

        rid = request_id_holder["id"]
        request = manager.get_request(rid)
        assert request is not None
        assert request.action == "delete_account"
        assert request.user_id == "user-2"
        assert request.status == ApprovalStatus.APPROVED


# ============================================================
# submit_review
# ============================================================

class TestSubmitReview:
    def test_submit_approved(self, manager):
        # 先创建一个待审批请求
        request = ApprovalRequest(
            request_id="HL-test-1",
            action="refund",
            description="测试退款",
            user_id="user-1",
        )
        manager._requests["HL-test-1"] = request

        ok = manager.submit_review(
            request_id="HL-test-1",
            approved=True,
            reviewer_id="admin",
            comment="同意退款",
        )
        assert ok is True
        assert request.status == ApprovalStatus.APPROVED
        assert request.reviewer_id == "admin"
        assert request.review_comment == "同意退款"
        assert request.reviewed_at is not None

    def test_submit_rejected(self, manager):
        request = ApprovalRequest(
            request_id="HL-test-2",
            action="delete_account",
            description="测试注销",
        )
        manager._requests["HL-test-2"] = request

        ok = manager.submit_review(
            request_id="HL-test-2",
            approved=False,
            reviewer_id="admin",
        )
        assert ok is True
        assert request.status == ApprovalStatus.REJECTED

    def test_submit_nonexistent_request_returns_false(self, manager):
        ok = manager.submit_review("HL-nonexistent", approved=True)
        assert ok is False

    def test_submit_already_reviewed_returns_false(self, manager):
        request = ApprovalRequest(
            request_id="HL-test-3",
            action="refund",
            description="已审批",
        )
        request.status = ApprovalStatus.APPROVED
        manager._requests["HL-test-3"] = request

        ok = manager.submit_review("HL-test-3", approved=False)
        assert ok is False

    def test_submit_without_reviewer_id(self, manager):
        request = ApprovalRequest(
            request_id="HL-test-4",
            action="refund",
            description="测试",
        )
        manager._requests["HL-test-4"] = request

        ok = manager.submit_review("HL-test-4", approved=True)
        assert ok is True
        assert request.reviewer_id == ""


# ============================================================
# get_request / list_pending
# ============================================================

class TestGetAndList:
    def test_get_request_returns_request(self, manager):
        request = ApprovalRequest(
            request_id="HL-get-1",
            action="refund",
            description="测试",
        )
        manager._requests["HL-get-1"] = request

        result = manager.get_request("HL-get-1")
        assert result is request

    def test_get_nonexistent_returns_none(self, manager):
        assert manager.get_request("HL-nonexistent") is None

    def test_list_pending_only_returns_pending(self, manager):
        r1 = ApprovalRequest(request_id="HL-1", action="a", description="d1")
        r2 = ApprovalRequest(request_id="HL-2", action="b", description="d2")
        r3 = ApprovalRequest(request_id="HL-3", action="c", description="d3")
        r3.status = ApprovalStatus.APPROVED

        manager._requests.update({
            "HL-1": r1, "HL-2": r2, "HL-3": r3,
        })

        pending = manager.list_pending()
        assert len(pending) == 2
        ids = {r.request_id for r in pending}
        assert ids == {"HL-1", "HL-2"}


# ============================================================
# 单例
# ============================================================

class TestSingleton:
    def test_get_humanloop_manager_returns_same_instance(self):
        m1 = get_humanloop_manager()
        m2 = get_humanloop_manager()
        assert m1 is m2

    def test_singleton_is_humanloop_manager(self):
        m = get_humanloop_manager()
        assert isinstance(m, HumanLoopManager)
