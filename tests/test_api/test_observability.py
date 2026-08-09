"""锁定可观测性链路（C 档核心交付）。

为什么需要这组测试：
    之前 Grafana 面板「JSON 合法、却永远 No data」的根因，不是 JSON 解析错，
    而是面板 expr 引用的指标名与后端真实吐出的指标名对不上（如
    llm_call_total vs llm_calls_total、漏写 _bucket、缺 service label）。
    本文件用交叉验证把这条链路焊死，任何一端改名都会红。

覆盖：
    1. metrics 模块渲染的 Prometheus 文本格式（累积桶 +Inf + sum/count）。
    2. 真实 HTTP 端点 /api/v1/metrics/prometheus 返回 200 且含关键指标。
    3. Grafana dashboard JSON 可被 json.load，且每个 panel 引用的指标名
       都属于「应用层已知指标 ∪ 外部 exporter 指标」，不允许凭空捏造。
    4. Prometheus 抓取路径 / 数据源 uid 与 dashboard 对齐（锁住配置修复）。
"""

import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.api import metrics as m  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def client():
    """构造 FastAPI TestClient（沿用仓库既有范式，app 在测试环境可安全 import）。"""
    from fastapi.testclient import TestClient

    from src.api.server import app

    return TestClient(app)

# ---- 应用层真实会吐出的指标（base 名，_bucket/_sum/_count 由 render 派生）----
APP_METRICS = {
    "http_requests_total",
    "http_request_duration_seconds",
    "http_request_duration_seconds_bucket",
    "llm_calls_total",
    "llm_calls_success_total",
    "llm_tokens_total",
    "ws_active_connections",
    "rag_search_duration_seconds",
    "rag_search_duration_seconds_bucket",
    "rag_search_total",
    "agent_quality_score_avg",
    "agent_resolution_rate",
    "agent_escalation_rate",
    "agent_requests_tracked_total",
}

# 依赖外部 exporter / Prometheus 自身的指标——本后端不吐，但面板合法
EXTERNAL_METRICS = {
    "up",
    "rabbitmq_queue_messages_ready",
    "milvus_num_entities",
    "redis_memory_used_bytes",
    "redis_memory_max_bytes",
    "ALERTS",
}

# PromQL 保留字/函数名——从 expr 抽取指标名时要剔除
PROMQL_RESERVED = {
    "sum", "rate", "irate", "histogram_quantile", "count", "avg", "max", "min",
    "by", "without", "le", "time", "and", "or", "unless", "on", "ignoring",
    "group_left", "group_right", "offset", "bool", "topk", "bottomk", "quantile",
    "increase", "delta", "idelta", "stddev", "stdvar", "abs", "ceil", "floor",
    "round", "clamp", "clamp_min", "clamp_max", "deriv", "predict_linear",
    "holt_winters", "reset", "changes", "resets", "label_replace", "label_join",
    "vector", "scalar", "absent", "absent_over_time", "timestamp",
}

DASHBOARD_PATH = os.path.join(
    ROOT, "deploy", "monitoring", "grafana", "dashboards", "agent-overview.json"
)
PROMETHEUS_PATH = os.path.join(ROOT, "deploy", "monitoring", "prometheus", "prometheus.yml")
DATASOURCES_PATH = os.path.join(ROOT, "deploy", "monitoring", "grafana", "datasources.yaml")


@pytest.fixture
def seeded():
    """播种若干指标家族，模拟真实运行后的内存状态。"""
    m.reset_metrics()
    m.counter_inc(
        "http_requests_total",
        {"service": "api", "endpoint": "/health", "status": "200", "method": "GET"},
    )
    m.histogram_observe(
        "http_request_duration_seconds", 0.03,
        {"service": "api", "endpoint": "/health", "method": "GET"},
    )
    m.record_llm_tokens(model="qwen-plus", prompt_tokens=120, completion_tokens=30,
                         tenant_id="default", success=True)
    m.gauge_set("agent_quality_score_avg", 0.9)
    m.gauge_set("agent_resolution_rate", 0.8)
    m.gauge_set("agent_escalation_rate", 0.1)
    m.gauge_set("ws_active_connections", 2, {"service": "websocket"})
    m.record_rag_search(0.12, backend="milvus", hit=True)
    yield m.render_metrics()
    m.reset_metrics()


def _metric_names_from_text(text: str) -> set:
    """从 Prometheus 文本格式抽取所有指标名（带后缀 _bucket/_sum/_count）。"""
    names = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        mobj = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s", line)
        if mobj:
            names.add(mobj.group(1))
    return names


def test_render_format_has_cumulative_buckets(seeded):
    """histogram 必须输出 _bucket{le} / _bucket{le=+Inf} / _sum / _count。"""
    text = seeded
    assert "http_request_duration_seconds_bucket" in text
    assert 'le="+Inf"' in text
    assert "http_request_duration_seconds_sum" in text
    assert "http_request_duration_seconds_count" in text
    # +Inf 桶计数应等于总观测数（此处 1 次 observe）
    inf_line = [l for l in text.splitlines() if 'le="+Inf"' in l]
    assert inf_line, "缺少 +Inf 桶"
    assert inf_line[0].strip().endswith("1")


def test_render_contains_key_app_metrics(seeded):
    names = _metric_names_from_text(seeded)
    for expected in {
        "http_requests_total",
        "http_request_duration_seconds_bucket",
        "llm_calls_total",
        "llm_calls_success_total",
        "llm_tokens_total",
        "agent_quality_score_avg",
        "ws_active_connections",
        "rag_search_duration_seconds_bucket",
    }:
        assert expected in names, f"渲染结果缺少关键指标 {expected}"


def test_http_metrics_endpoint(client):
    """真实端点 /api/v1/metrics/prometheus 返回 200 + 合法文本，且含业务 gauge。

    中间件在 finally 中记录本次请求，因此本次 scrape 渲染时还看不到自己；
    第二次 scrape 才包含第一次请求的 http_requests_total（与 Prometheus client
    库标准行为一致：本请求指标在下次抓取可见）。端点同时触发
    _refresh_business_gauges 把 agent_* 刷成 gauge。
    """
    resp = client.get("/api/v1/metrics/prometheus")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/plain")
    resp2 = client.get("/api/v1/metrics/prometheus")
    names = _metric_names_from_text(resp2.text)
    assert "http_requests_total" in names  # 第一次 GET 被记录，第二次 scrape 可见
    assert "agent_quality_score_avg" in names  # collect-on-scrape 刷新
    assert 'le="+Inf"' in resp2.text  # histogram 格式必须含 +Inf 桶


def test_dashboard_json_loadable():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        dash = json.load(f)
    assert "panels" in dash, "dashboard 缺 panels 字段"
    assert len(dash["panels"]) >= 10, "面板数量异常偏少"
    # provisioning 要求裸 dashboard 对象（无外层 {"dashboard": {...}} 包裹）
    assert "rows" not in dash or isinstance(dash.get("rows"), list)
    # 每个 panel 必须显式声明 datasource uid，否则 Grafana 找不到数据源
    for panel in dash["panels"]:
        ds = panel.get("datasource")
        assert ds and ds.get("uid") == "prometheus", (
            f"面板 {panel.get('id')} 未声明 datasource uid=prometheus"
        )


def test_dashboard_references_only_known_metrics():
    """每个 panel expr 引用的指标名，必须属于已知集合（应用层或外部 exporter）。

    这一步专门防「JSON 合法但面板 No data」——一旦后端指标改名，测试必红。
    """
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        dash = json.load(f)

    referenced = set()
    expr_re = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
    for panel in dash.get("panels", []):
        for t in panel.get("targets", []):
            expr = t.get("expr", "")
            # 去掉 label 选择器 {service="api"} —— 否则 label key 被误当指标
            expr = re.sub(r"\{[^}]*\}", "", expr)
            # 去掉 range 向量 [5m] —— 否则后缀 m/s 被误当指标
            expr = re.sub(r"\[[^\]]*\]", "", expr)
            # 去掉 by(...)/without(...) 分组子句 —— 否则里面的 label 名被误当指标
            expr = re.sub(r"\bby\s*\([^)]*\)", "", expr)
            expr = re.sub(r"\bwithout\s*\([^)]*\)", "", expr)
            for tok in expr_re.findall(expr):
                if tok in PROMQL_RESERVED:
                    continue
                referenced.add(tok)

    unknown = referenced - APP_METRICS - EXTERNAL_METRICS
    assert not unknown, f"面板引用了后端不存在的指标：{sorted(unknown)}"


def test_prometheus_scrape_path_matches_route():
    """Prometheus 抓取 api-service 的路径必须与后端真实路由一致。"""
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML 不可用，跳过配置校验")
    with open(PROMETHEUS_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    api_job = next(
        (j for j in cfg.get("scrape_configs", []) if j.get("job_name") == "api-service"),
        None,
    )
    assert api_job is not None, "缺少 api-service 抓取任务"
    assert api_job.get("metrics_path") == "/api/v1/metrics/prometheus", (
        "抓取路径与后端路由 /api/v1/metrics/prometheus 不一致"
    )


def test_datasource_uid_aligned():
    """Grafana 数据源 Prometheus 必须声明 uid=prometheus，与面板引用对齐。"""
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML 不可用，跳过配置校验")
    with open(DATASOURCES_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    prom = next(
        (d for d in cfg.get("datasources", []) if d.get("type") == "prometheus"),
        None,
    )
    assert prom is not None, "缺少 Prometheus 数据源"
    assert prom.get("uid") == "prometheus", "Prometheus 数据源未声明 uid=prometheus"
