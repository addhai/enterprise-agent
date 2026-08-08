"""RBAC 权限模块单元测试

覆盖：
- Permission 枚举完整性
- ROLE_PERMISSIONS 角色权限映射
- require_permissions 权限校验逻辑
- _perm_label 标签翻译
- /rbac/permissions 接口
"""
import pytest
from fastapi.testclient import TestClient

from src.api.rbac import (
    Permission,
    UserRole,
    ROLE_PERMISSIONS,
    _perm_label,
    require_permissions,
)


# ============================================================
# Permission 枚举测试
# ============================================================

class TestPermissionEnum:
    """Permission 枚举完整性测试"""

    def test_permission_set_is_expected(self):
        """权限点集合应与预期完全一致。

        用「显式集合」而非「魔数数量」做哨兵：新增/删除权限时，失败信息会
        直接指出多了或少了哪一个，而不是让人无脑把数字 +1，从而保留了
        「权限变更必须是有意识决定」这一契约的真实信号。
        """
        expected = {
            # P0 基础
            "dashboard:view",
            "customer:view", "customer:manage",
            "ticket:view", "ticket:manage", "ticket:assign",
            "agent:workspace",
            "satisfaction:view",
            "knowledge:view", "knowledge:manage",
            "channel:view", "channel:manage",
            "user:view", "user:manage",
            "notification:view",
            # P3-P6 扩展
            "config:view", "config:manage",
            "evaluation:view", "evaluation:manage",
            "workflow:view", "workflow:manage",
            "monitor:view",
        }
        actual = {p.value for p in Permission}
        assert actual == expected, (
            f"权限集合发生变化 — 新增: {actual - expected} / 移除: {expected - actual}"
        )

    def test_basic_permissions_exist(self):
        """基础权限点应存在"""
        assert Permission.DASHBOARD_VIEW.value == "dashboard:view"
        assert Permission.TICKET_MANAGE.value == "ticket:manage"
        assert Permission.USER_MANAGE.value == "user:manage"

    def test_new_permissions_exist(self):
        """P3-P6 新增权限应存在"""
        assert Permission.CONFIG_VIEW.value == "config:view"
        assert Permission.CONFIG_MANAGE.value == "config:manage"
        assert Permission.EVALUATION_VIEW.value == "evaluation:view"
        assert Permission.EVALUATION_MANAGE.value == "evaluation:manage"
        assert Permission.WORKFLOW_VIEW.value == "workflow:view"
        assert Permission.WORKFLOW_MANAGE.value == "workflow:manage"

    def test_permissions_unique(self):
        """权限值应唯一"""
        values = [p.value for p in Permission]
        assert len(values) == len(set(values)), "存在重复的权限值"


# ============================================================
# 角色权限映射测试
# ============================================================

class TestRolePermissions:
    """角色权限映射测试"""

    def test_super_admin_has_all_permissions(self):
        """super_admin 应拥有全部权限"""
        assert len(ROLE_PERMISSIONS[UserRole.SUPER_ADMIN]) == len(Permission)

    def test_admin_has_all_except_user_manage_limitation(self):
        """admin 应拥有除 user:manage 外的全部权限。

        断言「缺失集合」而非「数量」：这才是该角色真正的契约 —— 只有用户管理
        属于 super_admin 专属。新增任何权限点若忘记授予 admin，这里会精确报出。
        """
        admin_perms = set(ROLE_PERMISSIONS[UserRole.ADMIN])
        missing = set(Permission) - admin_perms
        assert missing == {Permission.USER_MANAGE}, (
            f"admin 权限缺口不符合预期，实际缺失: {[p.value for p in missing]}"
        )

    def test_agent_has_view_only_for_new_modules(self):
        """agent 对新增模块应只有 view 权限"""
        agent_perms = ROLE_PERMISSIONS[UserRole.AGENT]
        assert Permission.CONFIG_VIEW in agent_perms
        assert Permission.CONFIG_MANAGE not in agent_perms
        assert Permission.EVALUATION_VIEW in agent_perms
        assert Permission.EVALUATION_MANAGE not in agent_perms
        assert Permission.WORKFLOW_VIEW in agent_perms
        assert Permission.WORKFLOW_MANAGE not in agent_perms

    def test_viewer_has_view_only_for_new_modules(self):
        """viewer 对新增模块应只有 view 权限"""
        viewer_perms = ROLE_PERMISSIONS[UserRole.VIEWER]
        assert Permission.CONFIG_VIEW in viewer_perms
        assert Permission.CONFIG_MANAGE not in viewer_perms
        assert Permission.EVALUATION_VIEW in viewer_perms
        assert Permission.EVALUATION_MANAGE not in viewer_perms
        assert Permission.WORKFLOW_VIEW in viewer_perms
        assert Permission.WORKFLOW_MANAGE not in viewer_perms

    def test_agent_cannot_manage_users(self):
        """agent 不应有 user:manage 权限"""
        agent_perms = ROLE_PERMISSIONS[UserRole.AGENT]
        assert Permission.USER_MANAGE not in agent_perms
        assert Permission.USER_VIEW not in agent_perms

    def test_all_roles_have_dashboard_view(self):
        """所有角色都应有 dashboard:view 权限"""
        for role in UserRole:
            assert Permission.DASHBOARD_VIEW in ROLE_PERMISSIONS[role], \
                f"{role.value} 缺少 dashboard:view 权限"


# ============================================================
# _perm_label 标签翻译测试
# ============================================================

class TestPermLabel:
    """权限标签翻译测试"""

    def test_basic_labels(self):
        """基础权限应有中文标签"""
        assert _perm_label(Permission.DASHBOARD_VIEW) == "查看仪表盘"
        assert _perm_label(Permission.TICKET_VIEW) == "查看工单"

    def test_new_module_labels(self):
        """新增模块权限应有中文标签"""
        assert _perm_label(Permission.CONFIG_VIEW) == "查看配置"
        assert _perm_label(Permission.CONFIG_MANAGE) == "修改配置"
        assert _perm_label(Permission.EVALUATION_VIEW) == "查看评估"
        assert _perm_label(Permission.EVALUATION_MANAGE) == "管理评估"
        assert _perm_label(Permission.WORKFLOW_VIEW) == "查看工作流"
        assert _perm_label(Permission.WORKFLOW_MANAGE) == "管理工作流"

    def test_all_permissions_have_labels(self):
        """所有权限都应有非空标签（不应回退到 value）"""
        for perm in Permission:
            label = _perm_label(perm)
            assert label != perm.value, f"{perm.value} 缺少中文标签"
            assert len(label) > 0


# ============================================================
# require_permissions 权限校验逻辑测试
# ============================================================

class TestRequirePermissions:
    """权限校验工厂函数测试"""

    def test_require_permissions_returns_callable(self):
        """require_permissions 应返回可调用对象"""
        checker = require_permissions(Permission.DASHBOARD_VIEW)
        assert callable(checker)

    @pytest.mark.asyncio
    async def test_admin_passes_config_manage(self):
        """admin 用户应通过 config:manage 校验"""
        checker = require_permissions(Permission.CONFIG_MANAGE)
        # 模拟 admin 用户
        admin_user = {"user_id": "admin", "role": "admin"}
        # checker 是 async 函数，应正常返回
        result = await checker(current_user=admin_user)
        assert result["user_id"] == "admin"

    @pytest.mark.asyncio
    async def test_agent_blocked_from_config_manage(self):
        """agent 用户应被 config:manage 校验拒绝（403）"""
        from fastapi import HTTPException
        checker = require_permissions(Permission.CONFIG_MANAGE)
        agent_user = {"user_id": "agent", "role": "agent"}
        with pytest.raises(HTTPException) as exc_info:
            await checker(current_user=agent_user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_blocked_from_evaluation_manage(self):
        """viewer 用户应被 evaluation:manage 校验拒绝"""
        from fastapi import HTTPException
        checker = require_permissions(Permission.EVALUATION_MANAGE)
        viewer_user = {"user_id": "viewer", "role": "viewer"}
        with pytest.raises(HTTPException) as exc_info:
            await checker(current_user=viewer_user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_passes_config_view(self):
        """viewer 用户应通过 config:view 校验"""
        checker = require_permissions(Permission.CONFIG_VIEW)
        viewer_user = {"user_id": "viewer", "role": "viewer"}
        result = await checker(current_user=viewer_user)
        assert result["user_id"] == "viewer"

    @pytest.mark.asyncio
    async def test_invalid_role_blocked(self):
        """无效角色应被拒绝（403）"""
        from fastapi import HTTPException
        checker = require_permissions(Permission.DASHBOARD_VIEW)
        invalid_user = {"user_id": "x", "role": "invalid_role"}
        with pytest.raises(HTTPException) as exc_info:
            await checker(current_user=invalid_user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_multiple_permissions_all_required(self):
        """多个权限要求时应全部满足才通过"""
        from fastapi import HTTPException
        checker = require_permissions(
            Permission.CONFIG_VIEW,
            Permission.CONFIG_MANAGE,
        )
        # admin 两个都有
        admin_user = {"user_id": "admin", "role": "admin"}
        result = await checker(current_user=admin_user)
        assert result["user_id"] == "admin"
        # viewer 只有 view，没有 manage
        viewer_user = {"user_id": "viewer", "role": "viewer"}
        with pytest.raises(HTTPException) as exc_info:
            await checker(current_user=viewer_user)
        assert exc_info.value.status_code == 403


# ============================================================
# /rbac/permissions 接口测试
# ============================================================

class TestRbacPermissionsApi:
    """/rbac/permissions 接口测试"""

    def test_list_permissions_no_auth_required(self):
        """/rbac/permissions 应无需认证即可访问（公开接口）"""
        from src.api.server import app
        client = TestClient(app)
        resp = client.get("/api/v1/rbac/permissions")
        assert resp.status_code == 200
        data = resp.json()
        # 与枚举保持同步（避免魔数），接口应完整暴露全部权限点
        assert len(data["permissions"]) == len(Permission)
        labels = [p["label"] for p in data["permissions"]]
        assert "查看配置" in labels
        assert "管理工作流" in labels

    def test_list_permissions_all_have_labels(self):
        """所有权限都应有非空 label"""
        from src.api.server import app
        client = TestClient(app)
        resp = client.get("/api/v1/rbac/permissions")
        data = resp.json()
        for perm in data["permissions"]:
            assert perm["label"], f"{perm['permission']} 缺少 label"
            assert perm["label"] != perm["permission"], \
                f"{perm['permission']} 的 label 等于 permission value"
