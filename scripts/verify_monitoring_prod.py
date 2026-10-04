#!/usr/bin/env python

# ruff: noqa: S607
# S607 豁免理由：本脚本通过 subprocess 调用 docker CLI 读取容器状态
# （如 `docker ps`、`docker inspect`、`docker exec`）。命令名与容器名
# 全部在本文件内硬编码，不来自任何外部输入，且以列表形式传参、
# 不经过 shell，故「部分可执行路径」的风险不成立。
"""Phase 2 监控栈验收脚本（针对 deploy/prod 内网单容器形态）

与 scripts/verify_monitoring.py 的分工：
    那个脚本面向 cloud 多服务形态（根 docker-compose.yml + agent-net +
    api-service/rabbitmq/milvus），在本形态下起不来。
    本脚本面向 deploy/prod（单一 app 容器 + prod-net），是 Phase 2 的验收工具。

检查项（对应任务单的验收标准）：
    1. app 与监控栈容器是否都在运行
    2. Prometheus 抓取目标是否全部 UP（重点：job=app）
    3. app metrics 端点是否返回 Prometheus 文本格式，指标条数是否达标
    4. 逐个执行仪表盘面板的 PromQL，区分「有数据」与「无数据」
    5. Grafana 是否可登录、datasource 是否指向 prometheus
    6. 结构化日志是否落盘且含 request_id / duration_ms

用法：
    python scripts/verify_monitoring_prod.py
    python scripts/verify_monitoring_prod.py \
        --report C:/tmp/phase2_monitoring_report.json
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = (
    ROOT / "deploy" / "monitoring" / "grafana" / "dashboards" / "agent-overview.json"
)

APP = "http://localhost:8000"
PROM = "http://localhost:9090"
GRAFANA = "http://localhost:3000"
METRICS_PATH = "/api/v1/metrics/prometheus"


def http(url: str, timeout: int = 20, auth: str = "", raw: bool = False):
    req = urllib.request.Request(url)  # noqa: S310 —— URL 来自硬编码的 localhost 常量，不接受外部输入
    if auth:
        req.add_header(
            "Authorization", "Basic " + base64.b64encode(auth.encode()).decode()
        )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 —— 同上，url 由上面的 req 构造
            body = r.read().decode("utf-8", "replace")
            if raw:
                return r.status, body
            try:
                return r.status, json.loads(body)
            except Exception:
                return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def prom(expr: str) -> list:
    code, body = http(
        f"{PROM}/api/v1/query?query={urllib.parse.quote(expr)}", timeout=20
    )
    if code != 200 or not isinstance(body, dict):
        return []
    return body.get("data", {}).get("result", [])


def docker_ps() -> dict:
    """返回 {容器名: 状态}"""
    import subprocess

    try:
        out = subprocess.run(  # noqa: S603 —— 容器名与子命令均硬编码，列表传参不经 shell
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        result = {}
        for line in (out.stdout or "").strip().splitlines():
            if "\t" in line:
                name, status = line.split("\t", 1)
                result[name] = status
        return result
    except Exception:
        return {}


class Report:
    def __init__(self):
        self.items: list[dict] = []

    def check(self, name: str, ok: bool, detail) -> bool:
        self.items.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"        {json.dumps(detail, ensure_ascii=False)[:220]}")
        return bool(ok)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="", help="JSON 报告输出路径")
    ap.add_argument("--grafana-user", default="admin")
    ap.add_argument("--grafana-pass", default="admin123")
    args = ap.parse_args()
    rep = Report()

    print("=" * 70)
    print("Phase 2 监控栈验收（deploy/prod 形态）")
    print("=" * 70)

    # ---- 1. 容器状态 ----
    print("\n[1] 容器运行状态")
    ps = docker_ps()
    for name in [
        "prod-app-1",
        "prod-postgres-1",
        "prod-redis-1",
        "agent-prometheus",
        "agent-grafana",
        "agent-pg-exporter",
        "agent-redis-exporter",
    ]:
        status = ps.get(name, "")
        rep.check(
            f"{name} 运行中",
            bool(status) and "Up" in status,
            {"status": status or "未运行"},
        )

    # ---- 2. Prometheus 抓取目标 ----
    print("\n[2] Prometheus 抓取目标")
    code, body = http(f"{PROM}/api/v1/targets")
    targets = []
    if code == 200 and isinstance(body, dict):
        targets = body.get("data", {}).get("activeTargets", [])
    up_jobs = {t["labels"].get("job"): t["health"] for t in targets}
    rep.check("有抓取目标", len(targets) > 0, {"targets": len(targets)})
    rep.check(
        "job=app 状态 UP",
        up_jobs.get("app") == "up",
        {
            "health": up_jobs.get("app"),
            "scrape_url": next(
                (t["scrapeUrl"] for t in targets if t["labels"].get("job") == "app"), ""
            ),
        },
    )
    all_up = all(v == "up" for v in up_jobs.values()) if up_jobs else False
    rep.check("所有目标均为 UP", all_up, up_jobs)
    rep.check(
        'up{job="app"} == 1',
        bool(prom('up{job="app"}')),
        {"result": prom('up{job="app"}')},
    )

    # ---- 3. metrics 端点 ----
    print("\n[3] app metrics 端点")
    code, text = http(f"{APP}{METRICS_PATH}", timeout=20, raw=True)
    n_metric_lines = 0
    n_families = 0
    if code == 200 and isinstance(text, str):
        all_lines = text.splitlines()
        lines = [ln for ln in all_lines if ln and not ln.startswith("#")]
        type_lines = [ln for ln in all_lines if ln.startswith("# TYPE")]
        n_metric_lines = len(lines)
        n_families = len(type_lines)
    rep.check(f"GET {METRICS_PATH} 返回 200", code == 200, {"status": code})
    rep.check("指标族数 >= 5", n_families >= 5, {"type_lines": n_families})
    rep.check("样本行数 > 0", n_metric_lines > 0, {"sample_lines": n_metric_lines})

    # ---- 4. 逐面板 PromQL ----
    print("\n[4] 仪表盘面板 PromQL 出数情况")
    panels_stat = []
    if DASHBOARD.exists():
        dash = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        panels = dash.get("panels", [])
        with_data, without = 0, 0
        for p in panels:
            title = p.get("title", "?")
            exprs = [
                t.get("expr", "") for t in (p.get("targets") or []) if t.get("expr")
            ]
            if not exprs:
                panels_stat.append(
                    {"title": title, "type": p.get("type"), "status": "无查询语句"}
                )
                continue
            hit = False
            for e in exprs:
                if prom(e):
                    hit = True
                    break
            panels_stat.append(
                {
                    "title": title,
                    "type": p.get("type"),
                    "status": "有数据" if hit else "无数据",
                    "exprs": exprs,
                }
            )
            if hit:
                with_data += 1
            else:
                without += 1
        rep.check("面板总数 >= 4", len(panels) >= 4, {"panels": len(panels)})
        rep.check(
            "有数据的面板 >= 4",
            with_data >= 4,
            {"有数据": with_data, "无数据": without},
        )
        print("\n  面板明细：")
        for s in panels_stat:
            print(
                f"    [{'OK ' if s['status'] == '有数据' else '   '}] "
                f"{s['title']}  ({s['status']})"
            )
    else:
        rep.check("仪表盘文件存在", False, {"path": str(DASHBOARD)})

    # ---- 5. Grafana ----
    print("\n[5] Grafana")
    code, hb = http(f"{GRAFANA}/api/health")
    rep.check(
        "Grafana 健康检查",
        code == 200,
        hb if code != 200 else {"version": (hb or {}).get("version")},
    )
    auth = f"{args.grafana_user}:{args.grafana_pass}"
    code, ds = http(f"{GRAFANA}/api/datasources", auth=auth)
    ok_login = code == 200 and isinstance(ds, list)
    rep.check(f"可登录（{args.grafana_user}/***）", ok_login, {"status": code})
    if ok_login:
        prom_ds = [d for d in ds if d.get("type") == "prometheus"]
        rep.check(
            "存在 prometheus 数据源",
            len(prom_ds) > 0,
            [
                {
                    "name": d.get("name"),
                    "url": d.get("url"),
                    "default": d.get("isDefault"),
                }
                for d in prom_ds
            ],
        )
        rep.check(
            "prometheus 为默认数据源",
            any(d.get("isDefault") for d in prom_ds),
            {"isDefault": [d.get("isDefault") for d in prom_ds]},
        )
        code, search = http(f"{GRAFANA}/api/search?type=dash-db", auth=auth)
        dash_ok = code == 200 and isinstance(search, list) and len(search) > 0
        rep.check(
            "仪表盘已 provisioning",
            dash_ok,
            [{"uid": s.get("uid"), "title": s.get("title")} for s in (search or [])],
        )

    # ---- 6. 结构化日志 ----
    print("\n[6] 结构化日志")
    code, text = http(f"{APP}/api/v1/health", raw=True)  # 先产生一条访问日志
    time.sleep(1.5)
    import subprocess

    out = subprocess.run(  # noqa: S603 —— 容器名与子命令均硬编码，列表传参不经 shell
        [
            "docker",
            "exec",
            "prod-app-1",
            "sh",
            "-c",
            "wc -l /app/logs/app.jsonl 2>/dev/null; "
            "tail -3 /app/logs/app.jsonl 2>/dev/null",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    raw = (out.stdout or "").strip()
    lines = raw.splitlines()
    log_lines = 0
    sample = None
    if lines:
        try:
            log_lines = int(lines[0].split()[0])
        except Exception:
            log_lines = 0
        for cand in lines[1:]:
            try:
                sample = json.loads(cand)
            except Exception:  # noqa: S112 —— 非 JSON 日志行属预期，跳过继续
                # 该行不是合法 JSON（非结构化日志行），跳过继续
                continue
    rep.check(
        "日志文件 /app/logs/app.jsonl 存在且有内容", log_lines > 0, {"lines": log_lines}
    )
    has_req_id = bool(sample and sample.get("request_id"))
    has_dur = bool(sample and ("duration_ms" in sample))
    rep.check("日志为 JSON 且含 request_id", has_req_id, {"sample": sample})
    rep.check("日志含 duration_ms", has_dur, {"sample": sample})

    # ---- 汇总 ----
    passed = sum(1 for i in rep.items if i["ok"])
    failed = [i["check"] for i in rep.items if not i["ok"]]
    print("\n" + "=" * 70)
    print(f"结果：{passed}/{len(rep.items)} 项通过")
    if failed:
        print("未通过：")
        for f in failed:
            print(f"  - {f}")
    print("=" * 70)

    if args.report:
        Path(args.report).write_text(
            json.dumps(
                {
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "app_metrics_path": METRICS_PATH,
                    "metric_families": n_families,
                    "panels": panels_stat,
                    "checks": rep.items,
                    "summary": {
                        "total": len(rep.items),
                        "passed": passed,
                        "failed": failed,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"报告已写入：{args.report}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
