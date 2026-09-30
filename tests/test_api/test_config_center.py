"""配置中心 v1 接口（/api/v1/config/*）与监控自检端点测试

与 tests/test_api/test_config.py 的分工：
    那个文件覆盖既有的 /admin/config/* 接口（保持不动）。
    本文件覆盖 Phase 3 新增的规范路径与能力：
      - 单字段读取/更新、敏感字段脱敏
      - 类型 / 范围 / 枚举校验（非法值必须被拒）
      - 只读配置返回 400 且提示需重启
      - 批量更新的「全有或全无」语义
      - 配置变更审计与历史查询
      - 热更新能力自描述
      - 监控自检端点
"""

import contextlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.server import app

    return TestClient(app)


@pytest.fixture
def admin_headers(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture
def viewer_headers(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "viewer", "password": "viewer123"}
    )
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture(autouse=True)
def restore_config():
    """测试后把改动过的字段还原，避免测试间与后续用例相互污染"""
    yield
    from src.api.config import (
        _UPDATABLE_FIELDS,
        _get_field_default,
        _is_sensitive,
        _set_field_value,
    )

    for field_name in _UPDATABLE_FIELDS:
        if _is_sensitive(field_name):
            continue
        # 个别字段在当前环境下重置会失败（如依赖外部服务的项），
        # 这里是「尽力恢复出厂设置」，失败不影响后续用例
        with contextlib.suppress(Exception):
            _set_field_value(field_name, _get_field_default(field_name))


# ============================================================
# GET /api/v1/config
# ============================================================


class TestListConfig:
    def test_returns_fields_with_metadata(self, client, admin_headers):
        resp = client.get("/api/v1/config", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        assert "config_version" in data
        assert len(data["items"]) == data["total"]

        sample = data["items"][0]
        for key in ("key", "type", "value", "default", "readonly", "hot", "category"):
            assert key in sample, f"缺少字段 {key}"

    def test_filter_by_category(self, client, admin_headers):
        resp = client.get("/api/v1/config?category=retrieval", headers=admin_headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items
        assert all(i["category"] == "retrieval" for i in items)
        assert any(i["key"] == "retrieval_top_k" for i in items)

    def test_unknown_category_returns_404(self, client, admin_headers):
        resp = client.get("/api/v1/config?category=no_such_cat", headers=admin_headers)
        assert resp.status_code == 404

    def test_viewer_can_read(self, client, viewer_headers):
        resp = client.get("/api/v1/config", headers=viewer_headers)
        assert resp.status_code == 200

    def test_requires_auth(self, client):
        assert client.get("/api/v1/config").status_code == 401


class TestSecretMasking:
    """敏感字段判定规则的单元测试

    注意这里**不用白名单里的真实字段**做断言。原因（实测）：
    可更新白名单里全是运行时调参项，本来就不该有凭据，
    改对判定规则后白名单里敏感字段数为 0。
    断言「白名单里必须有敏感字段」会把测试写死在一个错误前提上。
    正确做法是直接测规则本身：凭据类名字要判敏感，参数类名字不能误判。
    """

    def test_credential_like_names_are_sensitive(self):
        """凭据类字段名必须判为敏感"""
        from src.config_center.schema import is_sensitive

        for name in [
            "openai_api_key",
            "jwt_secret",
            "minio_secret_key",
            "access_token",
            "db_password",
            "aws_credential",
        ]:
            assert is_sensitive(name) is True, f"{name} 应判为敏感"

    def test_generation_params_are_not_sensitive(self):
        """生成/检索参数不能因名字含 token 子串被误判（实测缺陷回归）"""
        from src.config_center.schema import is_sensitive

        for name in [
            "llm_max_tokens",
            "retrieval_min_tokens",
            "llm_temperature",
            "kv_cache_tokens",  # 复数、计量语义
        ]:
            assert is_sensitive(name) is False, (
                f"{name} 是数量参数而非凭据，不应判为敏感"
            )

    def test_sensitive_rule_has_single_source_of_truth(self):
        """三处调用点必须给出同一结论，避免规则漂移"""
        from src.api.config import _is_sensitive
        from src.config_center.audit import is_sensitive_key
        from src.config_center.schema import is_sensitive
        from src.config_center.service import is_sensitive as svc_is_sensitive

        for name in ["openai_api_key", "llm_max_tokens", "chat_sessions_total"]:
            results = {
                is_sensitive(name),
                svc_is_sensitive(name),
                is_sensitive_key(name),
                _is_sensitive(name),
            }
            assert len(results) == 1, f"{name} 在三处判定结果不一致：{results}"

    def test_no_credential_field_in_updatable_whitelist(self):
        """白名单里不应出现凭据类字段（配置中心只管运行时参数）"""
        from src.api.config import _UPDATABLE_FIELDS
        from src.config_center.schema import is_sensitive

        leaked = sorted(f for f in _UPDATABLE_FIELDS if is_sensitive(f))
        assert not leaked, f"可更新白名单里出现了凭据类字段：{leaked}"

    def test_max_tokens_is_readable_and_writable(self, client, admin_headers):
        """llm_max_tokens 必须可读可写（曾被误判为敏感而两者皆不可）"""
        got = client.get("/api/v1/config/llm_max_tokens", headers=admin_headers)
        assert got.status_code == 200
        body = got.json()
        assert body["is_sensitive"] is False, "llm_max_tokens 不应被判为敏感"
        assert body["value"] != "", "llm_max_tokens 的值不应被脱敏置空"

        put = client.put(
            "/api/v1/config/llm_max_tokens",
            json={"value": 1024},
            headers=admin_headers,
        )
        assert put.status_code == 200, (
            f"llm_max_tokens 应可在线修改，实际 {put.status_code}: {put.json()}"
        )
        assert put.json()["new_value"] == 1024


# ============================================================
# GET /api/v1/config/{key}
# ============================================================


class TestGetSingleConfig:
    def test_get_existing_key(self, client, admin_headers):
        resp = client.get("/api/v1/config/retrieval_top_k", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "retrieval_top_k"
        assert data["hot"] is True
        assert data["readonly"] is False
        assert data["category"] == "retrieval"

    def test_nonexistent_key_returns_404(self, client, admin_headers):
        resp = client.get("/api/v1/config/no_such_key_xyz", headers=admin_headers)
        assert resp.status_code == 404

    def test_readonly_key_is_readable(self, client, admin_headers):
        """只读字段仍是合法配置项，可以读，只是不能改"""
        resp = client.get("/api/v1/config/database_url", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["readonly"] is True


# ============================================================
# PUT /api/v1/config/{key}
# ============================================================


class TestUpdateSingleConfig:
    def test_update_and_verify(self, client, admin_headers):
        from src.config import settings

        resp = client.put(
            "/api/v1/config/retrieval_top_k",
            json={"value": 9},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["changed"] is True
        assert settings.retrieval_top_k == 9

        # 再读一次确认已生效
        got = client.get("/api/v1/config/retrieval_top_k", headers=admin_headers)
        assert got.json()["value"] == 9

    def test_invalid_type_rejected(self, client, admin_headers):
        resp = client.put(
            "/api/v1/config/retrieval_top_k",
            json={"value": "abc"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "retrieval_top_k" in resp.json()["detail"]

    def test_negative_value_rejected_by_range(self, client, admin_headers):
        """范围校验：top_k 最小为 1，负数必须被拒"""
        resp = client.put(
            "/api/v1/config/retrieval_top_k", json={"value": -3}, headers=admin_headers
        )
        assert resp.status_code == 400
        assert "不能小于" in resp.json()["detail"]

    def test_out_of_range_float_rejected(self, client, admin_headers):
        """相似度阈值超出 0~1 必须被拒（否则检索会静默失效）"""
        resp = client.put(
            "/api/v1/config/kb_similarity_threshold",
            json={"value": 5.0},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_enum_violation_rejected(self, client, admin_headers):
        resp = client.put(
            "/api/v1/config/kb_call_mode",
            json={"value": "sometimes"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "只接受" in resp.json()["detail"]

    def test_readonly_returns_400_with_restart_hint(self, client, admin_headers):
        resp = client.put(
            "/api/v1/config/database_url",
            json={"value": "postgresql://x/y"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "重启" in resp.json()["detail"]

    def test_nonexistent_key_returns_404(self, client, admin_headers):
        resp = client.put(
            "/api/v1/config/no_such_key_xyz", json={"value": 1}, headers=admin_headers
        )
        assert resp.status_code == 404

    def test_viewer_cannot_write(self, client, viewer_headers):
        resp = client.put(
            "/api/v1/config/retrieval_top_k", json={"value": 7}, headers=viewer_headers
        )
        assert resp.status_code == 403


# ============================================================
# PATCH /api/v1/config/batch
# ============================================================


class TestBatchUpdate:
    def test_batch_success(self, client, admin_headers):
        from src.config import settings

        resp = client.patch(
            "/api/v1/config/batch",
            json={"updates": {"retrieval_top_k": 6, "llm_temperature": 0.3}},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["updated_count"] == 2
        assert settings.retrieval_top_k == 6
        assert settings.llm_temperature == 0.3

    def test_all_or_nothing_semantics(self, client, admin_headers):
        """批量更新「全有或全无」：一项非法则整批不改，避免半生效的中间态"""
        from src.config import settings

        before = settings.retrieval_top_k
        resp = client.patch(
            "/api/v1/config/batch",
            json={"updates": {"retrieval_top_k": 8, "kb_similarity_threshold": 99.0}},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert settings.retrieval_top_k == before, "整批应被拒绝，合法项也不得生效"

    def test_empty_updates_rejected(self, client, admin_headers):
        resp = client.patch(
            "/api/v1/config/batch", json={"updates": {}}, headers=admin_headers
        )
        assert resp.status_code == 400


# ============================================================
# 审计
# ============================================================


class TestConfigAudit:
    def test_change_is_recorded(self, client, admin_headers):
        client.put(
            "/api/v1/config/retrieval_top_k",
            json={"value": 11},
            headers=admin_headers,
        )
        resp = client.get(
            "/api/v1/config/audit?key=retrieval_top_k&limit=5", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        latest = data["items"][0]
        assert latest["config_key"] == "retrieval_top_k"
        assert latest["new_value"] == "11"
        assert latest["operator"]
        assert latest["created_at"]

    def test_readonly_attempt_is_not_recorded(self, client, admin_headers):
        """被拒绝的更新不应产生审计记录（否则审计会被失败尝试污染）"""
        resp = client.get(
            "/api/v1/config/audit?key=database_url&limit=5", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ============================================================
# 热更新能力自描述
# ============================================================


class TestHotCategories:
    def test_at_least_five_hot_categories(self, client, admin_headers):
        """验收要求至少 5 类配置支持热更新"""
        resp = client.get("/api/v1/config/hot-categories", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_categories"] >= 5
        for cat, fields in data["categories"].items():
            assert fields, f"分类 {cat} 没有可用字段"

    def test_readonly_fields_not_marked_hot(self, client, admin_headers):
        item = client.get("/api/v1/config/database_url", headers=admin_headers).json()
        assert item["hot"] is False
        assert item["readonly"] is True


# ============================================================
# 监控自检
# ============================================================


class TestMonitoringSelfCheck:
    def test_self_check_returns_subsystem_status(self, client, admin_headers):
        resp = client.get("/api/v1/monitoring/self-check", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        checks = data["checks"]
        for key in ("metrics", "logs", "config_center", "dependencies"):
            assert key in checks, f"缺少子系统检查 {key}"
        # 配置中心应可读
        assert checks["config_center"]["ok"] is True
        assert "version" in checks["config_center"]

    def test_self_check_requires_auth(self, client):
        assert client.get("/api/v1/monitoring/self-check").status_code == 401


class TestStrictTypeValidation:
    """严格类型校验：布尔字段只接受真正的布尔值

    原实现会把 "yes"/"on"/"1" 宽松地当作真值接受，使客户端的笔误
    （把布尔写成字符串）静默变成一次成功写入。配置是长期生效的东西，
    宁可当场 400，也不要替调用方猜。
    """

    @pytest.mark.parametrize("bad", ['"yes"', '"on"', '"1"', '"true"', "1"])
    def test_bool_field_rejects_non_boolean(self, client, admin_headers, bad):
        resp = client.put(
            "/api/v1/config/rerank_enabled",
            content=f'{{"value": {bad}}}',
            headers={**admin_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400, (
            f"布尔字段不应接受 {bad}，实际 {resp.status_code}: {resp.json()}"
        )
        assert "布尔值" in resp.json()["detail"]

    def test_bool_field_accepts_real_boolean(self, client, admin_headers):
        resp = client.put(
            "/api/v1/config/rerank_enabled",
            json={"value": True},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["new_value"] is True
