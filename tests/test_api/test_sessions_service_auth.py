"""会话归属/租户访问矩阵单测（2026-10 P0-3 收口 H3）

覆盖 sessions_service 的纯判定逻辑：
    - _session_access_allowed：用户归属 + 租户双维度
    - delete_session_checked：404 / 403 / 200 三态

不触 DB 与网络：归属查询与实际删除都被 monkeypatch 成桩。
"""

import pytest
import src.api.sessions_service as svc


def _user(user_id="u1", role="viewer", tenant_id="default"):
    return {"user_id": user_id, "role": role, "tenant_id": tenant_id}


def _owner(user_id="u1", tenant_id="default"):
    return {"user_id": user_id, "tenant_id": tenant_id}


class TestSessionAccessAllowed:
    def test_owner_same_tenant_allowed(self):
        assert svc._session_access_allowed(_user(), _owner()) is True

    def test_other_user_same_tenant_denied_for_viewer(self):
        assert (
            svc._session_access_allowed(
                _user(user_id="attacker"), _owner(user_id="victim")
            )
            is False
        )

    def test_agent_can_read_other_user_in_same_tenant(self):
        """客服需要查看本租户客户会话"""
        assert (
            svc._session_access_allowed(
                _user(user_id="agent-1", role="agent"),
                _owner(user_id="customer-9"),
            )
            is True
        )

    def test_admin_cross_tenant_denied(self):
        """租户隔离对管理员同样生效"""
        assert (
            svc._session_access_allowed(
                _user(role="admin", tenant_id="default"),
                _owner(user_id="anyone", tenant_id="tenant-b"),
            )
            is False
        )

    def test_super_admin_cross_tenant_denied(self):
        assert (
            svc._session_access_allowed(
                _user(role="super_admin", tenant_id="default"),
                _owner(user_id="anyone", tenant_id="tenant-b"),
            )
            is False
        )

    def test_anonymous_denied_even_if_owner_empty(self):
        assert svc._session_access_allowed(None, _owner(user_id="")) is False

    def test_tenant_missing_defaults_to_default(self):
        """历史数据无 tenant_id 时归一 default，default 租户用户可见"""
        assert (
            svc._session_access_allowed(
                _user(user_id="u1"), _owner(user_id="u1", tenant_id="default")
            )
            is True
        )


class TestSessionOwnerAllowed:
    """用户端 /sessions 严格本人判定（角色不豁免，master 原有边界）。"""

    def test_owner_same_tenant_allowed(self):
        assert svc._session_owner_allowed(_user(), _owner()) is True

    def test_other_user_denied_for_viewer(self):
        assert (
            svc._session_owner_allowed(
                _user(user_id="attacker"), _owner(user_id="victim")
            )
            is False
        )

    def test_agent_role_not_exempt(self):
        """自注册用户默认 role=agent，用户端不得借此读到他人会话"""
        assert (
            svc._session_owner_allowed(
                _user(user_id="agent-1", role="agent"),
                _owner(user_id="customer-9"),
            )
            is False
        )

    def test_super_admin_role_not_exempt(self):
        assert (
            svc._session_owner_allowed(
                _user(user_id="admin-1", role="super_admin"),
                _owner(user_id="customer-9"),
            )
            is False
        )

    def test_owner_cross_tenant_denied(self):
        """同名 user_id 跨租户也拒绝（user_id 非全局唯一的纵深防线）"""
        assert (
            svc._session_owner_allowed(
                _user(user_id="u1", tenant_id="default"),
                _owner(user_id="u1", tenant_id="tenant-b"),
            )
            is False
        )

    def test_anonymous_denied(self):
        assert svc._session_owner_allowed(None, _owner()) is False


class TestDeleteSessionCheckedOwnerOnly:
    @pytest.fixture(autouse=True)
    def _stub_delete(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            svc, "delete_session", lambda sid: calls.append(sid) or True
        )
        self.delete_calls = calls

    def _set_owner(self, monkeypatch, owner):
        monkeypatch.setattr(svc, "get_session_ownership", lambda sid: owner)

    def test_agent_cannot_delete_other_user_owner_only(self, monkeypatch):
        self._set_owner(monkeypatch, _owner(user_id="customer-9"))
        with pytest.raises(PermissionError):
            svc.delete_session_checked(
                "s-1",
                _user(user_id="agent-1", role="agent"),
                owner_only=True,
            )
        assert self.delete_calls == []

    def test_owner_can_delete_owner_only(self, monkeypatch):
        self._set_owner(monkeypatch, _owner(user_id="u1"))
        assert svc.delete_session_checked("s-1", _user(), owner_only=True) is True
        assert self.delete_calls == ["s-1"]

    def test_anonymous_denied_owner_only(self, monkeypatch):
        self._set_owner(monkeypatch, _owner(user_id="u1"))
        with pytest.raises(PermissionError):
            svc.delete_session_checked("s-1", None, owner_only=True)
        assert self.delete_calls == []


class TestDeleteSessionChecked:
    @pytest.fixture(autouse=True)
    def _stub_delete(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            svc, "delete_session", lambda sid: calls.append(sid) or True
        )
        self.delete_calls = calls

    def _set_owner(self, monkeypatch, owner):
        monkeypatch.setattr(svc, "get_session_ownership", lambda sid: owner)

    def test_missing_session_returns_none(self, monkeypatch):
        self._set_owner(monkeypatch, None)
        assert svc.delete_session_checked("s-x", _user(role="admin")) is None
        assert self.delete_calls == []

    def test_other_user_denied(self, monkeypatch):
        self._set_owner(monkeypatch, _owner(user_id="victim"))
        with pytest.raises(PermissionError):
            svc.delete_session_checked("s-1", _user(user_id="attacker"))
        assert self.delete_calls == []

    def test_cross_tenant_admin_denied(self, monkeypatch):
        self._set_owner(monkeypatch, _owner(user_id="c1", tenant_id="tenant-b"))
        with pytest.raises(PermissionError):
            svc.delete_session_checked("s-1", _user(role="admin", tenant_id="default"))
        assert self.delete_calls == []

    def test_anonymous_denied(self, monkeypatch):
        self._set_owner(monkeypatch, _owner(user_id="victim"))
        with pytest.raises(PermissionError):
            svc.delete_session_checked("s-1", None)
        assert self.delete_calls == []

    def test_agent_same_tenant_deletes(self, monkeypatch):
        self._set_owner(monkeypatch, _owner(user_id="customer-9", tenant_id="default"))
        assert (
            svc.delete_session_checked("s-1", _user(user_id="agent-1", role="agent"))
            is True
        )
        assert self.delete_calls == ["s-1"]

    def test_owner_self_delete(self, monkeypatch):
        self._set_owner(monkeypatch, _owner(user_id="u1"))
        assert svc.delete_session_checked("s-1", _user()) is True
        assert self.delete_calls == ["s-1"]
