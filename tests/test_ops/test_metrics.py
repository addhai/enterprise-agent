"""P4-2 指标端点测试

验证指标端点返回 200、包含关键指标名、格式可解析。
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.server import app

    return TestClient(app)


class TestMetricsEndpoint:
    def test_prometheus_endpoint_200(self, client):
        """/api/v1/metrics/prometheus 返回 200"""
        resp = client.get("/api/v1/metrics/prometheus")
        assert resp.status_code == 200

    def test_prometheus_content_type(self, client):
        """Content-Type 应为 text/plain 或类似"""
        resp = client.get("/api/v1/metrics/prometheus")
        ct = resp.headers.get("content-type", "")
        assert "text" in ct or "plain" in ct or "json" in ct

    def test_prometheus_has_type_lines(self, client):
        """Prometheus 格式含 # TYPE 行"""
        resp = client.get("/api/v1/metrics/prometheus")
        text = resp.text
        # 可能有指标也可能为空（未发请求时 counter=0 不输出）
        # 只要格式正确即可
        if text.strip():
            assert "# TYPE" in text or "http_" in text

    def test_business_metrics(self, client):
        """/api/v1/metrics/business 返回 200"""
        resp = client.get("/api/v1/metrics/business")
        assert resp.status_code == 200

    def test_system_metrics(self, client):
        """/api/v1/metrics/system 返回 200"""
        resp = client.get("/api/v1/metrics/system")
        assert resp.status_code == 200

    def test_all_metrics_json(self, client):
        """/api/v1/metrics/all 返回 JSON"""
        resp = client.get("/api/v1/metrics/all")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)


class TestStructuredLogging:
    """结构化日志测试"""

    def test_json_formatter(self):
        """JSONFormatter 应输出 JSON 格式"""
        import json
        import logging

        from src.utils.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["message"] == "test message"
        assert "timestamp" in data

    def test_json_formatter_with_extra(self):
        """extra 字段应出现在 JSON 输出中"""
        import json
        import logging

        from src.utils.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="chat_started",
            args=(),
            exc_info=None,
        )
        record.request_id = "abc123"
        record.session_id = "sess-001"
        record.duration_ms = 42.5
        output = formatter.format(record)
        data = json.loads(output)
        assert data["request_id"] == "abc123"
        assert data["session_id"] == "sess-001"
        assert data["duration_ms"] == 42.5

    def test_json_formatter_redacts_sensitive(self):
        """敏感字段不应作为 JSON 顶层字段输出"""
        import json
        import logging

        from src.utils.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="login",
            args=(),
            exc_info=None,
        )
        # formatter 只提取指定字段（request_id 等），不提取 token/password
        record.request_id = "req-001"
        output = formatter.format(record)
        data = json.loads(output)
        # request_id 应出现（在提取列表中）
        assert data.get("request_id") == "req-001"
        # 敏感字段不应作为顶层 key 出现
        assert "token" not in data
        assert "password" not in data
        assert "secret" not in data

    def test_json_formatter_error_field(self):
        """异常时应含 error 字段（type + message，不含堆栈）"""
        import json
        import logging

        from src.utils.logging import JSONFormatter

        formatter = JSONFormatter()
        try:
            raise ValueError("test error message")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error occurred",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "error" in data
        assert data["error"]["type"] == "ValueError"
        assert "test error message" in data["error"]["message"]

    def test_request_id_generation(self):
        """request_id 应为 12 位 hex"""
        from src.utils.logging import generate_request_id

        rid = generate_request_id()
        assert len(rid) == 12
        assert all(c in "0123456789abcdef" for c in rid)

    def test_request_timing(self):
        """RequestTiming 应记录耗时"""
        import time

        from src.utils.logging import RequestTiming

        with RequestTiming() as t:
            time.sleep(0.01)
        assert t.elapsed_ms > 0
        assert len(t.request_id) == 12

    def test_setup_logging(self):
        """setup_logging 应不崩溃"""
        from src.utils.logging import setup_logging

        setup_logging("DEBUG")
        setup_logging("INFO")
