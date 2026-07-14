"""
API 监控指标 — Prometheus /metrics 端点

提供:
  - 请求计数 (按 endpoint + status)
  - 请求延迟 Histogram
  - LLM 调用计数/错误
  - WebSocket 活跃连接数
  - RAG 检索延迟
  - 对话质量评分
"""

from __future__ import annotations

import time
from typing import Dict, Optional

# ---- 轻量级 Prometheus 指标（不依赖 prometheus_client 库）----
# 生产环境建议 pip install prometheus-client 并替换为此处实现
# 当前使用纯 Python 实现，避免额外依赖

_counts: Dict[str, int] = {}
_histograms: Dict[str, list] = {}
_gauges: Dict[str, float] = {}


def _key(name: str, labels: dict = None) -> str:
    """生成 metric key"""
    if not labels:
        return name
    pairs = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f'{name}{{{pairs}}}'


def counter_inc(name: str, labels: dict = None, value: int = 1):
    """计数器 +1"""
    k = _key(name, labels)
    _counts[k] = _counts.get(k, 0) + value


def histogram_observe(name: str, value: float, labels: dict = None):
    """Histogram 记录"""
    k = _key(name, labels)
    if k not in _histograms:
        _histograms[k] = []
    _histograms[k].append(value)


def gauge_set(name: str, value: float, labels: dict = None):
    """Gauge 设置"""
    k = _key(name, labels)
    _gauges[k] = value


def gauge_inc(name: str, value: float = 1, labels: dict = None):
    """Gauge +1"""
    k = _key(name, labels)
    _gauges[k] = _gauges.get(k, 0) + value


def gauge_dec(name: str, value: float = 1, labels: dict = None):
    """Gauge -1"""
    k = _key(name, labels)
    _gauges[k] = _gauges.get(k, 0) - value


# ---- Metrics 端点 ----

def render_metrics() -> str:
    """渲染 Prometheus text format 输出"""
    lines = []
    now_ms = int(time.time() * 1000)

    # Counters
    for k, v in sorted(_counts.items()):
        lines.append(f"# TYPE {k.split('{')[0]} counter")
        lines.append(f"{k} {v}")

    # Histograms (simplified: 只输出 sum + count)
    for k, values in sorted(_histograms.items()):
        base = k.split("{")[0]
        lines.append(f"# TYPE {base} histogram")
        lines.append(f"{base}_sum{k[len(base):] if '{' in k else ''} {sum(values):.6f}")
        lines.append(f"{base}_count{k[len(base):] if '{' in k else ''} {len(values)}")

    # Gauges
    for k, v in sorted(_gauges.items()):
        lines.append(f"# TYPE {k.split('{')[0]} gauge")
        lines.append(f"{k} {v:.6f}")

    return "\n".join(lines) + "\n"


class MetricsMiddleware:
    """FastAPI 中间件：自动收集请求指标"""

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return

        start = time.time()
        status_code = 500
        path = scope.get("path", "/")

        try:

            async def send_wrapper(message):
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                await send(message)

            # 调用下一个中间件/路由
            await self.app(scope, receive, send_wrapper)

        finally:
            elapsed = time.time() - start
            endpoint = _normalize_path(path)
            counter_inc("http_requests_total", {"endpoint": endpoint, "status": str(status_code), "method": scope.get("method", "GET")})
            histogram_observe("http_request_duration_seconds", elapsed, {"endpoint": endpoint, "method": scope.get("method", "GET")})


def _normalize_path(path: str) -> str:
    """将动态路径参数标准化为形参名"""
    import re
    # /api/v1/chat → chat
    # /health → health
    # /ws/session/xxx/chat → /ws/session/:session_id/chat
    path = re.sub(r'/api/v\d+/', '/', path)
    path = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-', ':uuid', path)
    return path


async def metrics_endpoint():
    """Prometheus /metrics 端点"""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(render_metrics(), media_type="text/plain; charset=utf-8")
