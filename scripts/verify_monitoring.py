"""docker 版「Grafana 面板真能出数」验证（需 docker daemon）

C 档已修复 Grafana 面板/配置，并写了 tests/test_api/test_observability.py 锁死
“面板引用的指标名 ⊆ 后端真实吐出的指标名”。但那只是静态/格式校验。本脚本
把链路真正跑起来：起 prometheus + grafana，等 Prometheus 抓取后端若干轮后，
用 Prometheus 数据源逐面板执行 agent-overview.json 里的 PromQL，断言返回非空
（证明面板不是“JSON 合法却空白”）。

前置：
  - docker daemon 已启动
  - 后端 /api/v1/metrics/prometheus 可达（本机起 backend，或同一 compose 网络）
  - prometheus.yml 的 scrape 路径已对齐 /api/v1/metrics/prometheus（C 档已修）

运行：
  python scripts/verify_monitoring.py
退出码 0 = 所有面板 PromQL 均返回非空；非 0 = 存在空白面板。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONITORING_COMPOSE = os.path.join(ROOT, "docker-compose.monitoring.yml")
DASHBOARD = os.path.join(ROOT, "deploy", "monitoring", "grafana", "dashboards", "agent-overview.json")
PROM_URL = "http://127.0.0.1:9090"
BACKEND_METRICS = "http://127.0.0.1:8000/api/v1/metrics/prometheus"
POLL = 120  # 等 Prometheus 抓取若干轮

PROMQL_RESERVED = {
    "by", "without", "on", "group_left", "group_right", "offset", "bool",
    "and", "or", "unless", "ignoring", "rate", "sum", "avg", "count", "max",
    "min", "histogram_quantile", "increase", "irate", "topk", "bottomk",
    "le", "inf", "nan", "count_values", "stddev", "stdvar", "quantile",
}


def _log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _panel_metrics(expr: str) -> set[str]:
    """从 PromQL 抽取指标名（去掉 range 向量、by/without 子句、label 块）。"""
    e = re.sub(r"\[[^\]]*\]", "", expr)          # 去 [5m] 等
    e = re.sub(r"\b(by|without)\s*\([^)]*\)", "", e)  # 去 by (le)
    e = re.sub(r"\{[^}]*\}", "", e)             # 去 {label=...}
    toks = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", e)
    return {t for t in toks if t not in PROMQL_RESERVED}


def _wait_prometheus():
    deadline = time.time() + POLL
    while time.time() < deadline:
        try:
            import urllib.request
            r = urllib.request.urlopen(f"{PROM_URL}/-/ready", timeout=3)
            if r.status == 200:
                return True
        except Exception:
            time.sleep(3)
    return False


def _query(expr: str) -> list:
    import urllib.request
    url = f"{PROM_URL}/api/v1/query?query=" + __import__("urllib.parse").quote(expr)
    r = urllib.request.urlopen(url, timeout=15)
    data = json.loads(r.read().decode())
    return data.get("data", {}).get("result", [])


def main():
    _log("=== Grafana panels render with data (docker) ===")
    rc, out = _run(["docker", "compose", "-f", MONITORING_COMPOSE, "up", "-d"])
    if rc != 0:
        _log(f"FAIL: monitoring stack up failed\n{out}")
        return 2
    if not _wait_prometheus():
        _log("FAIL: prometheus not ready")
        return 3
    _log(f"prometheus ready, waiting {POLL}s for scrape cycles...")
    time.sleep(POLL)

    with open(DASHBOARD, encoding="utf-8") as f:
        dash = json.load(f)
    panels = dash.get("panels", [])
    total = 0
    empty = 0
    for p in panels:
        for t in p.get("targets", []):
            expr = t.get("expr", "")
            if not expr:
                continue
            total += 1
            try:
                res = _query(expr)
            except Exception as e:
                _log(f"  panel '{p.get('title')}' query err: {e}")
                empty += 1
                continue
            if not res:
                _log(f"  EMPTY panel '{p.get('title')}' expr={expr[:60]}...")
                empty += 1
            else:
                _log(f"  OK panel '{p.get('title')}' -> {len(res)} series")
    if empty:
        _log(f"FAIL: {empty}/{total} panels returned no data")
        return 4
    _log(f"=== RESULT: all {total} panels return data (Grafana render verified) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
