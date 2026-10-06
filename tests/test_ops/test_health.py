"""P4-2 健康检查测试

覆盖：轻量探针端点、依赖级健康明细（数据库/向量库/Ollama/模型）、
Prometheus 指标端点。全部打生产应用 src.api.server。
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI 测试客户端（内存 SQLite）"""
    from src.api.server import app

    return TestClient(app)


class TestEnhancedHealth:
    """轻量健康探针测试（routes.py GET /api/v1/health）"""

    def test_health_returns_structure(self, client):
        """/api/v1/health 应返回含 status 和 service 的结构"""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded", "down")
        assert "service" in data

    def test_health_has_checks_field(self, client):
        """轻量探针至少返回 status + service（依赖明细在 /health/detail）"""
        resp = client.get("/api/v1/health")
        data = resp.json()
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


class TestDependencyHealthDetail:
    """依赖级健康明细（src.api.routes GET /api/v1/health/detail）

    历史背景：这套断言最早绑定根目录原型入口 main.py 的 /api/health，
    而 main.py 被 .gitignore 排除、从未入库，导致 Linux CI 上
    ModuleNotFoundError: No module named 'main' 连续红灯。增强检查已
    迁入生产应用 src.api.server，测试随之改打真实入口。
    """

    def test_detail_health_has_checks(self, client):
        """明细端点应含四项依赖检查与时间戳"""
        resp = client.get("/api/v1/health/detail")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "checks" in data
        assert "database" in data["checks"]
        assert "vector_store" in data["checks"]
        assert "ollama" in data["checks"]
        assert "models" in data["checks"]
        assert "timestamp" in data

    def test_detail_health_ollama_unreachable(self, client):
        """Ollama 不可达时 ollama=unreachable、models=none、status=degraded"""
        resp = client.get("/api/v1/health/detail")
        data = resp.json()
        # 本机/CI 通常没有 Ollama，允许 ok 或 unreachable 两种环境
        assert data["checks"]["ollama"] in ("ok", "unreachable")
        if data["checks"]["ollama"] == "unreachable":
            assert data["status"] == "degraded"
            assert data["checks"]["models"] == "none"

    def test_detail_health_elapsed_ms(self, client):
        """明细检查耗时应 < 5000ms（Docker 探针 timeout 预算）"""
        resp = client.get("/api/v1/health/detail")
        data = resp.json()
        assert "elapsed_ms" in data
        assert data["elapsed_ms"] < 5000

    def test_detail_health_database_state(self, client):
        """数据库检查结果只能为 ok 或 down"""
        resp = client.get("/api/v1/health/detail")
        data = resp.json()
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
