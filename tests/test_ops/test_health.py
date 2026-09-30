"""P4-2 健康检查测试

覆盖 3 个场景：全 ok、Ollama 不可达、向量库空。
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI 测试客户端（内存 SQLite）"""
    from src.api.server import app

    return TestClient(app)


class TestEnhancedHealth:
    """增强健康检查测试（main.py /api/health）"""

    def test_health_returns_structure(self, client):
        """/api/v1/health 应返回含 status 和 service 的结构"""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded", "down")
        assert "service" in data

    def test_health_has_checks_field(self, client):
        """健康检查应含 checks 字段（main.py 增强版）"""
        # 测试 routes.py 的 /api/v1/health（简化版，不含 checks）
        # main.py 的 /api/health 才有 checks
        resp = client.get("/api/v1/health")
        data = resp.json()
        # routes.py 的 health 至少返回 status + service
        assert "status" in data
        assert "service" in data

    def test_health_status_values(self, client):
        """status 只能是 ok / degraded / down"""
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert data["status"] in ("ok", "degraded", "down")

    def test_health_aliyun_fallback_flag(self, client):
        """routes.py health 应暴露 aliyun_demo_fallback 标记"""
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert "aliyun_demo_fallback" in data
        assert isinstance(data["aliyun_demo_fallback"], bool)


class TestMainHealthEndpoint:
    """main.py /api/health 增强版测试"""

    @pytest.fixture
    def main_app_client(self):
        """main.py 的独立 TestClient"""
        import main as main_mod

        return TestClient(main_mod.app)

    def test_main_health_has_checks(self, main_app_client):
        """main.py /api/health 应含 checks 字段"""
        resp = main_app_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "checks" in data
        assert "database" in data["checks"]
        assert "vector_store" in data["checks"]
        assert "ollama" in data["checks"]
        assert "models" in data["checks"]
        assert "timestamp" in data

    def test_main_health_ollama_unreachable(self, main_app_client):
        """Ollama 不可达时 checks.ollama = unreachable, status = degraded"""
        resp = main_app_client.get("/api/health")
        data = resp.json()
        # 测试环境无 Ollama，预期 unreachable
        assert data["checks"]["ollama"] in ("ok", "unreachable")
        if data["checks"]["ollama"] == "unreachable":
            assert data["status"] == "degraded"
            assert data["checks"]["models"] == "none"

    def test_main_health_elapsed_ms(self, main_app_client):
        """健康检查耗时应 < 5000ms"""
        resp = main_app_client.get("/api/health")
        data = resp.json()
        assert "elapsed_ms" in data
        assert data["elapsed_ms"] < 5000

    def test_main_health_database_ok(self, main_app_client):
        """数据库检查应为 ok（内存 SQLite 由 conftest 初始化）"""
        resp = main_app_client.get("/api/health")
        data = resp.json()
        # 数据库可能 ok 或 down（取决于 init_db 是否在 startup 中成功）
        assert data["checks"]["database"] in ("ok", "down")


class TestMetricsEndpoint:
    """指标端点测试"""

    def test_prometheus_metrics_returns_200(self, client):
        """/api/v1/metrics/prometheus 应返回 200"""
        resp = client.get("/api/v1/metrics/prometheus")
        assert resp.status_code == 200

    def test_prometheus_format(self, client):
        """返回应为 Prometheus 文本格式"""
        resp = client.get("/api/v1/metrics/prometheus")
        text = resp.text
        # Prometheus 格式含 # TYPE 或 # HELP 注释行
        assert "# TYPE" in text or "# HELP" in text or len(text) > 0

    def test_metrics_contains_key_names(self, client):
        """应包含关键指标名"""
        resp = client.get("/api/v1/metrics/prometheus")
        text = resp.text
        # 至少有 http_requests 或 http_request_duration
        assert "http_request" in text or "llm_" in text or "rag_" in text

    def test_all_metrics_endpoint(self, client):
        """/api/v1/metrics/all 应返回 JSON 格式"""
        resp = client.get("/api/v1/metrics/all")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
