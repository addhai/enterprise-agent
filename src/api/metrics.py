"""
API 监控指标 — Prometheus /metrics 端点

提供:
  - 请求计数 (按 service + endpoint + method + status)
  - 请求延迟 Histogram（真实 bucket，支持 histogram_quantile）
  - LLM 调用计数 / 成功计数 / token 用量
  - WebSocket 活跃连接数
  - RAG 检索延迟
  - Agent 注册中心状态

设计说明
--------
不依赖 prometheus_client 库（保持零额外依赖），但输出严格遵循
Prometheus text exposition format，Grafana / Prometheus 可直接消费。

Histogram 使用**累积桶计数**而非保存原始样本：
  - 保存原始样本会随请求量无限增长（内存泄漏）
  - 累积桶是 Prometheus 官方 histogram 的标准实现方式
  - 输出 _bucket{le="..."} / _sum / _count 三件套，
    histogram_quantile() 才能计算 P50/P95/P99
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional

# ---- 轻量级 Prometheus 指标（不依赖 prometheus_client 库）----

# 服务标识：多副本/多服务部署时区分指标来源（api / ws / rag）
# Grafana 面板通过 {service="api"} 过滤，缺这个 label 面板会跨服务混算
SERVICE_NAME = os.getenv("SERVICE_NAME", "api")

# 默认延迟分桶（秒）—— 覆盖 5ms ~ 10s，适配 API 与 RAG 检索场景
DEFAULT_BUCKETS: tuple = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)

_lock = threading.Lock()

_counts: Dict[str, int] = {}
_gauges: Dict[str, float] = {}
# histogram key -> {"buckets": [count...], "sum": float, "count": int}
_histograms: Dict[str, dict] = {}


def _key(name: str, labels: Optional[dict] = None) -> str:
    """生成 metric key，label 按字母序排列保证同一组合只有一个 key"""
    if not labels:
        return name
    pairs = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{pairs}}}"


def _split_key(k: str) -> tuple:
    """把 'name{a="1"}' 拆成 ('name', '{a="1"}')；无 label 时后者为空串"""
    if "{" in k:
        base, rest = k.split("{", 1)
        return base, "{" + rest
    return k, ""


def _merge_labels(label_str: str, extra: str) -> str:
    """向已有 label 串中追加一个 label（用于 histogram 的 le=）"""
    if not label_str:
        return "{" + extra + "}"
    return label_str[:-1] + "," + extra + "}"


def counter_inc(name: str, labels: Optional[dict] = None, value: int = 1):
    """计数器累加"""
    k = _key(name, labels)
    with _lock:
        _counts[k] = _counts.get(k, 0) + value


def histogram_observe(name: str, value: float, labels: Optional[dict] = None):
    """Histogram 记录一次观测值（累积桶，内存恒定）"""
    k = _key(name, labels)
    with _lock:
        h = _histograms.get(k)
        if h is None:
            h = {"buckets": [0] * len(DEFAULT_BUCKETS), "sum": 0.0, "count": 0}
            _histograms[k] = h
        for i, upper in enumerate(DEFAULT_BUCKETS):
            if value <= upper:
                h["buckets"][i] += 1
        h["sum"] += value
        h["count"] += 1


def gauge_set(name: str, value: float, labels: Optional[dict] = None):
    """Gauge 设置"""
    k = _key(name, labels)
    with _lock:
        _gauges[k] = value


def gauge_inc(name: str, value: float = 1, labels: Optional[dict] = None):
    """Gauge 累加"""
    k = _key(name, labels)
    with _lock:
        _gauges[k] = _gauges.get(k, 0) + value


def gauge_dec(name: str, value: float = 1, labels: Optional[dict] = None):
    """Gauge 递减"""
    k = _key(name, labels)
    with _lock:
        _gauges[k] = _gauges.get(k, 0) - value


def reset_metrics():
    """清空所有指标（仅供测试使用）"""
    with _lock:
        _counts.clear()
        _gauges.clear()
        _histograms.clear()


# ---- LLM 调用与 Token 用量 ----
# 输出示例：llm_tokens_total{model="qwen-plus",type="prompt",tenant="t1"} 12345


def record_llm_tokens(
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    tenant_id: str = "default",
    success: bool = True,
):
    """记录一次 LLM 调用的 token 消耗与调用结果

    Args:
        model: 模型名（如 qwen-plus / qwen-max）
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数
        tenant_id: 租户 ID（用于按租户统计成本）
        success: 本次调用是否成功（用于计算成功率 SLO）
    """
    if prompt_tokens > 0:
        counter_inc(
            "llm_tokens_total",
            {"model": model, "type": "prompt", "tenant": tenant_id},
            prompt_tokens,
        )
    if completion_tokens > 0:
        counter_inc(
            "llm_tokens_total",
            {"model": model, "type": "completion", "tenant": tenant_id},
            completion_tokens,
        )
    # 总调用次数 +1
    counter_inc("llm_calls_total", {"model": model, "tenant": tenant_id})
    # 成功调用单独计数：成功率 = llm_calls_success_total / llm_calls_total
    if success:
        counter_inc("llm_calls_success_total", {"model": model, "tenant": tenant_id})


def record_rag_search(duration_seconds: float, backend: str = "unknown", hit: bool = True):
    """记录一次 RAG 检索的耗时与命中情况

    Grafana「RAG Search Latency」面板依赖 rag_search_duration_seconds_bucket。
    """
    histogram_observe(
        "rag_search_duration_seconds", duration_seconds, {"backend": backend}
    )
    counter_inc("rag_search_total", {"backend": backend, "hit": str(hit).lower()})


# ---- Metrics 渲染 ----


def render_metrics() -> str:
    """渲染 Prometheus text exposition format 输出"""
    lines: List[str] = []

    with _lock:
        counts = dict(_counts)
        gauges = dict(_gauges)
        histograms = {k: {**v, "buckets": list(v["buckets"])} for k, v in _histograms.items()}

    # Counters —— 同名指标的 TYPE 行只输出一次（Prometheus 规范要求）
    emitted_types = set()
    for k, v in sorted(counts.items()):
        base, _ = _split_key(k)
        if base not in emitted_types:
            lines.append(f"# TYPE {base} counter")
            emitted_types.add(base)
        lines.append(f"{k} {v}")

    # Histograms —— 输出 _bucket / _sum / _count 三件套
    for k, h in sorted(histograms.items()):
        base, label_str = _split_key(k)
        if base not in emitted_types:
            lines.append(f"# TYPE {base} histogram")
            emitted_types.add(base)
        cumulative = 0
        for i, upper in enumerate(DEFAULT_BUCKETS):
            cumulative = h["buckets"][i]
            le_labels = _merge_labels(label_str, f'le="{upper}"')
            lines.append(f"{base}_bucket{le_labels} {cumulative}")
        # +Inf 桶等于总观测数，Prometheus 规范强制要求
        inf_labels = _merge_labels(label_str, 'le="+Inf"')
        lines.append(f'{base}_bucket{inf_labels} {h["count"]}')
        lines.append(f'{base}_sum{label_str} {h["sum"]:.6f}')
        lines.append(f'{base}_count{label_str} {h["count"]}')

    # Gauges
    for k, v in sorted(gauges.items()):
        base, _ = _split_key(k)
        if base not in emitted_types:
            lines.append(f"# TYPE {base} gauge")
            emitted_types.add(base)
        lines.append(f"{k} {v:.6f}")

    return "\n".join(lines) + "\n"


# ---- ASGI 中间件 ----


class MetricsMiddleware:
    """纯 ASGI 中间件：自动收集 HTTP 请求指标

    注意（历史 bug）：
      1. 原实现缺少 __init__(self, app)，self.app 不存在，实例化即不可用；
      2. 原实现对非 http scope 直接 return 而不转发，会让 WebSocket 与
         lifespan 事件全部失效。二者叠加导致该中间件从未被挂载。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # 非 HTTP 流量（websocket / lifespan）必须原样转发，否则整个应用挂掉
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.time()
        status_code = 500
        path = scope.get("path", "/")
        method = scope.get("method", "GET")

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.time() - start
            endpoint = _normalize_path(path)
            counter_inc(
                "http_requests_total",
                {
                    "service": SERVICE_NAME,
                    "endpoint": endpoint,
                    "status": str(status_code),
                    "method": method,
                },
            )
            histogram_observe(
                "http_request_duration_seconds",
                elapsed,
                {"service": SERVICE_NAME, "endpoint": endpoint, "method": method},
            )


_UUID_RE = None


def _normalize_path(path: str) -> str:
    """将动态路径参数标准化，避免高基数 label 撑爆 Prometheus

    /api/v1/tickets/9f8e7d6c-1234-... → /tickets/:uuid
    """
    global _UUID_RE
    if _UUID_RE is None:
        import re

        _UUID_RE = re.compile(
            r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        )
    import re

    path = re.sub(r"/api/v\d+/", "/", path)
    path = _UUID_RE.sub("/:uuid", path)
    # 纯数字 ID 段同样折叠，防止 label 基数爆炸
    path = re.sub(r"/\d+(?=/|$)", "/:id", path)
    return path or "/"


async def metrics_endpoint():
    """Prometheus /metrics 端点"""
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(render_metrics(), media_type="text/plain; charset=utf-8")
