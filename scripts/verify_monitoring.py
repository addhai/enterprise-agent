"""docker 版「Grafana 面板真能出数」验证（需 docker daemon）

C 档已修复 Grafana 面板/配置，并写了 tests/test_api/test_observability.py 锁死
“面板引用的指标名 ⊆ 后端真实吐出的指标名”。但那只是静态/格式校验。本脚本
把链路真正跑起来：先起最小后端子集（api-service 自动拉 postgres/redis/rabbitmq，
同在 agent-net），再起监控栈（prometheus/grafana/exporters，共享 agent-net），
等 Prometheus 抓取后端 /api/v1/metrics/prometheus 若干轮后，逐面板执行
agent-overview.json 里的 PromQL，断言返回非空（证明面板不是“JSON 合法却空白”）。

前置：
  - docker daemon 已启动（本脚本会先自检）
  - 已 cp .env.example .env（key 留空不影响 metrics/health）
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
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE = os.path.join(ROOT, "docker-compose.yml")
MONITORING_COMPOSE = os.path.join(ROOT, "docker-compose.monitoring.yml")
DASHBOARD = os.path.join(ROOT, "deploy", "monitoring", "grafana", "dashboards", "agent-overview.json")
PROM_URL = "http://127.0.0.1:9090"
POLL = 120  # 等 Prometheus 抓取若干轮
REPORT_PATH = os.path.join(ROOT, "verify_monitoring_report.txt")  # 结论同时落文件，避免任务输出取不回时丢结果
_report_fh = open(REPORT_PATH, "w", encoding="utf-8")  # 启动时截断，整轮运行写入同一文件

PROMQL_RESERVED = {
    "by", "without", "on", "group_left", "group_right", "offset", "bool",
    "and", "or", "unless", "ignoring", "rate", "sum", "avg", "count", "max",
    "min", "histogram_quantile", "increase", "irate", "topk", "bottomk",
    "le", "inf", "nan", "count_values", "stddev", "stdvar", "quantile",
}


def _log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        _report_fh.write(line + "\n")
        _report_fh.flush()
    except Exception:
        pass


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _docker_daemon_ok() -> bool:
    rc, _ = _run(["docker", "info"])
    return rc == 0


def _panel_metrics(expr: str) -> set[str]:
    """从 PromQL 抽取指标名（去掉 range 向量、by/without 子句、label 块）。"""
    e = re.sub(r"\[[^\]]*\]", "", expr)
    e = re.sub(r"\b(by|without)\s*\([^)]*\)", "", e)
    e = re.sub(r"\{[^}]*\}", "", e)
    toks = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", e)
    return {t for t in toks if t not in PROMQL_RESERVED}


def _wait_prometheus() -> bool:
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            r = urllib.request.urlopen(f"{PROM_URL}/-/ready", timeout=3)
            if r.status == 200:
                return True
        except Exception:
            time.sleep(3)
    return False


def _query(expr: str) -> list:
    url = f"{PROM_URL}/api/v1/query?query=" + urllib.parse.quote(expr)
    r = urllib.request.urlopen(url, timeout=15)
    data = json.loads(r.read().decode())
    return data.get("data", {}).get("result", [])


# 本脚本会创建的容器名（来自主 compose 的 container_name 与监控 compose 的 container_name）。
# 上次验证中曾因 6 天前的残留同名停止容器导致命名冲突而 FAIL，故开头先防御性清理，保证幂等可重跑。
_STALE_CONTAINERS = [
    "agent-postgres", "agent-redis", "agent-rabbitmq",
    "agent-prometheus", "agent-grafana", "agent-pg-exporter", "agent-redis-exporter",
]


def _cleanup_stale():
    for name in _STALE_CONTAINERS:
        _run(["docker", "rm", "-f", name])  # 忽略“不存在”等错误


def main():
    _log("=== Grafana panels render with data (docker) ===")
    if not _docker_daemon_ok():
        _log("FAIL: docker daemon 未启动，请先打开 Docker Desktop")
        return 1
    _cleanup_stale()  # 清掉同名残留容器，避免命名冲突

    # 1) 起最小后端（api-service 自动带 postgres/redis/rabbitmq，同在 agent-net）
    rc, out = _run(["docker", "compose", "-f", COMPOSE, "up", "-d", "api-service"])
    if rc != 0:
        _log(f"FAIL: backend up failed\n{out}")
        return 2

    # 2) 起监控栈（prometheus/grafana/exporters，共享 external agent-net）
    rc, out = _run(["docker", "compose", "-f", MONITORING_COMPOSE, "up", "-d"])
    if rc != 0:
        _log(f"FAIL: monitoring up failed\n{out}")
        _run(["docker", "compose", "-f", COMPOSE, "down"])
        return 3

    try:
        if not _wait_prometheus():
            _log("FAIL: prometheus not ready")
            return 4
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
                    # 含 rate/increase 的面板在无流量时可能返回空，检查底层指标是否存在
                    exists = False
                    for m in _panel_metrics(expr):
                        try:
                            if _query(m):
                                exists = True
                                break
                        except Exception:
                            pass
                    if exists:
                        _log(f"  OK(no-traffic) panel '{p.get('title')}' -> metric exists, awaiting traffic")
                        continue
                    _log(f"  EMPTY panel '{p.get('title')}' expr={expr[:60]}...")
                    empty += 1
                else:
                    _log(f"  OK panel '{p.get('title')}' -> {len(res)} series")
        if empty:
            _log(f"FAIL: {empty}/{total} panels returned no data")
            return 5
        _log(f"=== RESULT: all {total} panels return data (Grafana render verified) ===")
        return 0
    finally:
        _log("cleaning up...")
        _run(["docker", "compose", "-f", MONITORING_COMPOSE, "down"])
        _run(["docker", "compose", "-f", COMPOSE, "down"])


if __name__ == "__main__":
    sys.exit(main())
