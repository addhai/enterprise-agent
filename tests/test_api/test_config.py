"""配置中心 API 单元测试

覆盖：
- GET /admin/config（全量配置查询）
- GET /admin/config/{category}（分类查询）
- PUT /admin/config（热更新）
- GET/PUT /admin/config/features（Feature Flag）
- POST /admin/config/reset（重置）
- 权限校验（viewer 只读、agent 只读、admin 全权）
"""
import pytest
from fastapi.testclient import TestClient

from src.config import settings


@pytest.fixture
def client():
    """FastAPI 测试客户端"""
    from src.api.server import app
    # 默认账号（admin/agent/viewer）由 tests/conftest.py 的 _init_test_database
    # 在 session 级用内存 SQLite 完成建表 + seed，无需再手动初始化。
    return TestClient(app)


@pytest.fixture
def admin_headers(client):
    """admin 请求头"""
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "admin123",
    })
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture
def viewer_headers(client):
    """viewer 请求头"""
    resp = client.post("/api/v1/auth/login", json={
        "username": "viewer", "password": "viewer123",
    })
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture(autouse=True)
def reset_config_after_test():
    """每个测试后重置配置，避免测试间相互污染"""
    yield
    # 测试后重置所有改动
    from src.api.config import _UPDATABLE_FIELDS, _is_sensitive, _get_field_value, _get_field_default, _set_field_value
    for field_name in _UPDATABLE_FIELDS:
        if _is_sensitive(field_name):
            continue
        _set_field_value(field_name, _get_field_default(field_name))


# ============================================================
# GET /admin/config 测试
# ============================================================

class TestGetConfig:
    """GET /admin/config 接口测试"""

    def test_admin_can_list_all_config(self, client, admin_headers):
        """admin 应能获取所有配置"""
        resp = client.get("/api/v1/admin/config", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_categories"] >= 10
        assert len(data["categories"]) == data["total_categories"]

    def test_config_categories_have_required_fields(self, client, admin_headers):
        """每个分类应包含 key/label/description/fields"""
        resp = client.get("/api/v1/admin/config", headers=admin_headers)
        for cat in resp.json()["categories"]:
            assert "key" in cat
            assert "label" in cat
            assert "description" in cat
            assert "fields" in cat
            assert isinstance(cat["fields"], list)

    def test_config_fields_have_required_fields(self, client, admin_headers):
        """每个字段应包含 name/type/default/value/is_sensitive"""
        resp = client.get("/api/v1/admin/config", headers=admin_headers)
        for cat in resp.json()["categories"]:
            for field in cat["fields"]:
                assert "name" in field
                assert "type" in field
                assert "default" in field
                assert "value" in field
                assert "is_sensitive" in field

    def test_viewer_can_read_config(self, client, viewer_headers):
        """viewer 应能查看配置（只读）"""
        resp = client.get("/api/v1/admin/config", headers=viewer_headers)
        assert resp.status_code == 200

    def test_unauthenticated_cannot_access(self, client):
        """未认证应返回 401"""
        resp = client.get("/api/v1/admin/config")
        assert resp.status_code == 401


# ============================================================
# GET /admin/config/{category} 测试
# ============================================================

class TestGetConfigByCategory:
    """GET /admin/config/{category} 接口测试"""

    def test_get_existing_category(self, client, admin_headers):
        """获取存在的分类应成功"""
        resp = client.get("/api/v1/admin/config/llm", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "llm"
        assert "label" in data
        assert len(data["fields"]) > 0

    def test_get_nonexistent_category_returns_404(self, client, admin_headers):
        """不存在的分类应返回 404"""
        resp = client.get("/api/v1/admin/config/nonexistent_cat", headers=admin_headers)
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert "nonexistent_cat" in detail

    def test_get_rerank_category(self, client, admin_headers):
        """获取 rerank 分类应包含 rerank_enabled 字段"""
        resp = client.get("/api/v1/admin/config/rerank", headers=admin_headers)
        assert resp.status_code == 200
        field_names = [f["name"] for f in resp.json()["fields"]]
        assert "rerank_enabled" in field_names


# ============================================================
# PUT /admin/config 测试
# ============================================================

class TestUpdateConfig:
    """PUT /admin/config 接口测试"""

    def test_admin_can_update_bool_field(self, client, admin_headers):
        """admin 应能更新布尔字段"""
        # 确保初始值
        settings.rerank_enabled = False
        resp = client.put("/api/v1/admin/config", headers=admin_headers, json={
            "updates": {"rerank_enabled": True}
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["updated_count"] == 1
        assert settings.rerank_enabled is True

    def test_admin_can_update_int_field(self, client, admin_headers):
        """admin 应能更新 int 字段"""
        settings.retrieval_top_k = 5
        resp = client.put("/api/v1/admin/config", headers=admin_headers, json={
            "updates": {"retrieval_top_k": 10}
        })
        assert resp.status_code == 200
        assert settings.retrieval_top_k == 10

    def test_admin_can_update_float_field(self, client, admin_headers):
        """admin 应能更新 float 字段"""
        settings.kb_similarity_threshold = 0.2
        resp = client.put("/api/v1/admin/config", headers=admin_headers, json={
            "updates": {"kb_similarity_threshold": 0.5}
        })
        assert resp.status_code == 200
        assert settings.kb_similarity_threshold == 0.5

    def test_admin_can_update_multiple_fields(self, client, admin_headers):
        """admin 应能一次更新多个字段"""
        resp = client.put("/api/v1/admin/config", headers=admin_headers, json={
            "updates": {
                "rerank_enabled": True,
                "retrieval_top_k": 8,
                "kb_similarity_threshold": 0.3,
            }
        })
        assert resp.status_code == 200
        assert resp.json()["updated_count"] == 3

    def test_string_to_int_auto_coercion(self, client, admin_headers):
        """字符串数字应自动转换为 int"""
        settings.retrieval_top_k = 5
        resp = client.put("/api/v1/admin/config", headers=admin_headers, json={
            "updates": {"retrieval_top_k": "7"}
        })
        assert resp.status_code == 200
        assert settings.retrieval_top_k == 7
        assert isinstance(settings.retrieval_top_k, int)

    def test_invalid_type_rejected(self, client, admin_headers):
        """类型错误应被跳过并记录"""
        resp = client.put("/api/v1/admin/config", headers=admin_headers, json={
            "updates": {"kb_similarity_threshold": "not-a-number"}
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated_count"] == 0
        assert data["skipped_count"] == 1

    def test_non_whitelisted_field_rejected(self, client, admin_headers):
        """白名单外字段应被拒绝（如 openai_api_key）"""
        resp = client.put("/api/v1/admin/config", headers=admin_headers, json={
            "updates": {"openai_api_key": "sk-xxx"}
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated_count"] == 0
        assert data["skipped_count"] == 1
        assert data["skipped"][0]["field"] == "openai_api_key"

    def test_empty_updates_returns_400(self, client, admin_headers):
        """空更新应返回 400"""
        resp = client.put("/api/v1/admin/config", headers=admin_headers, json={
            "updates": {}
        })
        assert resp.status_code == 400

    def test_viewer_cannot_update(self, client, viewer_headers):
        """viewer 不能 PUT 配置（403）"""
        resp = client.put("/api/v1/admin/config", headers=viewer_headers, json={
            "updates": {"rerank_enabled": True}
        })
        assert resp.status_code == 403

    def test_unauthenticated_cannot_update(self, client):
        """未认证不能 PUT（401）"""
        resp = client.put("/api/v1/admin/config", json={
            "updates": {"rerank_enabled": True}
        })
        assert resp.status_code == 401


# ============================================================
# Feature Flag 测试
# ============================================================

class TestFeatureFlags:
    """GET/PUT /admin/config/features 接口测试"""

    def test_list_feature_flags(self, client, admin_headers):
        """应返回 Feature Flag 列表"""
        resp = client.get("/api/v1/admin/config/features", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        assert data["enabled"] + data["disabled"] == data["total"]
        for flag in data["flags"]:
            assert "name" in flag
            assert "enabled" in flag
            assert "category" in flag

    def test_toggle_flag_on(self, client, admin_headers):
        """admin 应能开启 Feature Flag"""
        settings.guardrail_llm_jailbreak = False
        resp = client.put(
            "/api/v1/admin/config/features/guardrail_llm_jailbreak",
            headers=admin_headers,
            json={"enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
        assert settings.guardrail_llm_jailbreak is True

    def test_toggle_flag_off(self, client, admin_headers):
        """admin 应能关闭 Feature Flag"""
        settings.rerank_enabled = True
        resp = client.put(
            "/api/v1/admin/config/features/rerank_enabled",
            headers=admin_headers,
            json={"enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
        assert settings.rerank_enabled is False

    def test_toggle_nonexistent_flag_returns_404(self, client, admin_headers):
        """不存在的 flag 应返回 404"""
        resp = client.put(
            "/api/v1/admin/config/features/nonexistent_flag",
            headers=admin_headers,
            json={"enabled": True},
        )
        assert resp.status_code == 404

    def test_toggle_non_bool_field_returns_400(self, client, admin_headers):
        """非布尔字段应返回 400"""
        resp = client.put(
            "/api/v1/admin/config/features/llm_model",
            headers=admin_headers,
            json={"enabled": True},
        )
        assert resp.status_code == 400

    def test_viewer_cannot_toggle_flag(self, client, viewer_headers):
        """viewer 不能切换 Flag（403）"""
        resp = client.put(
            "/api/v1/admin/config/features/rerank_enabled",
            headers=viewer_headers,
            json={"enabled": True},
        )
        assert resp.status_code == 403


# ============================================================
# 重置接口测试
# ============================================================

class TestResetConfig:
    """POST /admin/config/reset 接口测试"""

    def test_reset_category(self, client, admin_headers):
        """应能重置指定分类"""
        # 先修改
        settings.rerank_enabled = True
        settings.rerank_top_n = 99
        # 重置
        resp = client.post("/api/v1/admin/config/reset/rerank", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # 验证已重置
        assert settings.rerank_enabled is False
        assert settings.rerank_top_n == 5

    def test_reset_all(self, client, admin_headers):
        """应能重置所有配置"""
        # 先修改多个
        settings.rerank_enabled = True
        settings.llm_model = "qwen-turbo"
        settings.max_reasoning_turns = 10
        # 重置
        resp = client.post("/api/v1/admin/config/reset", headers=admin_headers)
        assert resp.status_code == 200
        # 验证已重置
        assert settings.rerank_enabled is False
        assert settings.llm_model == "qwen-plus"
        assert settings.max_reasoning_turns == 5

    def test_reset_nonexistent_category_returns_404(self, client, admin_headers):
        """重置不存在的分类应 404"""
        resp = client.post("/api/v1/admin/config/reset/nonexistent", headers=admin_headers)
        assert resp.status_code == 404

    def test_viewer_cannot_reset(self, client, viewer_headers):
        """viewer 不能重置（403）"""
        resp = client.post("/api/v1/admin/config/reset", headers=viewer_headers)
        assert resp.status_code == 403


# ============================================================
# Meta 接口测试
# ============================================================

class TestConfigMeta:
    """GET /admin/config/meta/categories 接口测试"""

    def test_list_categories(self, client, admin_headers):
        """应返回分类清单"""
        resp = client.get("/api/v1/admin/config/meta/categories", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 10
        for cat in data["categories"]:
            assert "key" in cat
            assert "label" in cat
            assert "field_count" in cat
