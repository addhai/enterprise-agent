#!/usr/bin/env python3
"""金标题库检索基线：宿主编排器。

把 questions.yaml 转 JSON，连同容器内 worker 一起 docker cp 进生产
app 容器执行，取回报告并落两份产物：
  scripts/golden/reports/retrieval_<时间戳>.json  逐题明细（机器读）
  scripts/golden/reports/retrieval_<时间戳>.md    汇总+失题清单（人读）

判分完全发生在容器内（真实索引、真实检索链路），宿主机只做搬运。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

# 题库 2026-10-08 起冻结：检索基线评测前强制校验内容锁
from bank_lock import ensure_frozen_or_exit

CONTAINER_Q = "/tmp/golden_questions.json"  # noqa: S108 - 容器内固定中转路径
CONTAINER_WORKER = "/tmp/golden_eval_retrieval.py"  # noqa: S108
CONTAINER_REPORT = "/tmp/golden_report.json"  # noqa: S108
WORKER = Path(__file__).with_name("eval_retrieval.py")


def docker(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    # 固定参数数组调用受控 docker CLI，无 shell 注入面
    return subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            *args,
        ],
        capture_output=capture,
        text=True,
        check=False,
    )


def render_markdown(report: dict) -> str:
    lines = [
        "# 金标题库检索基线报告",
        "",
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- top_k：{report['top_k']}，计分题数：{report['scored']}，"
        f"跳过：{report['skipped']}",
        f"- 文档命中率：**{report['doc_hit_rate_pct']}%**",
        f"- PDF 页码准确率：**{report['page_hit_rate_pct']}%**",
        f"- 文档 MRR：{report['doc_mrr']}",
        f"- 平均检索耗时：{report['latency_ms']['avg']}ms，"
        f"峰值：{report['latency_ms']['max']}ms",
    ]
    if report["errors"]:
        lines.append(f"- 异常题目：{', '.join(report['errors'])}")
    lines += [
        "",
        "## 分类型指标",
        "",
        "| 类型 | 题数 | 文档命中率 | 页码题数 | 页码准确率 |",
        "|------|------|-----------|---------|-----------|",
    ]
    type_name = {
        "fact": "事实定位",
        "synthesis": "跨章综合",
        "procedure": "操作流程",
        "refusal": "拒答越界",
    }
    for t in ("fact", "synthesis", "procedure", "refusal"):
        m = report["by_type"].get(t)
        if not m:
            continue
        lines.append(
            f"| {type_name[t]} | {m['total']} | {m['doc_hit_rate_pct']}% "
            f"| {m['page_total']} | {m['page_hit_rate_pct']}% |"
        )

    lines += ["", "## 未完全命中的题（doc_only / miss / error）", ""]
    bad_verdicts = ("doc_only", "miss", "error")
    bad = [r for r in report["rows"] if r.get("verdict") in bad_verdicts]
    if not bad:
        lines.append("全部命中。")
    for r in bad:
        lines.append(f"### {r['id']} [{r['type']}] {r['verdict']}")
        lines.append(f"- 问：{r['question']}")
        lines.append(f"- 期望文档：{', '.join(r['gold_docs']) or '（无，库外题）'}")
        if r.get("page_details"):
            for doc_name, d in r["page_details"].items():
                lines.append(
                    f"- 页码核对 {doc_name}：期望 {d['allowed_pages']}，"
                    f"实际命中 {d['matched_pages'] or '无'}"
                )
        if r.get("error"):
            lines.append(f"- 异常：{r['error']}")
        top = (r.get("retrieved") or [])[:5]
        if top:
            shown = ", ".join(
                f"{h['rank']}.{h['source']}"
                + (f"#p{h['page']}" if h.get("page") else "")
                for h in top
            )
            lines.append(f"- top5 命中：{shown}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default="tests/golden/questions.yaml")
    ap.add_argument("--container", default="prod-app-1")
    ap.add_argument("--out-dir", default="scripts/golden/reports")
    args = ap.parse_args()

    bank = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))
    ensure_frozen_or_exit(Path(args.questions))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    with tempfile.TemporaryDirectory() as td:
        q_path = Path(td) / "questions.json"
        q_path.write_text(
            json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        steps = [
            ("cp", ["cp", str(q_path), f"{args.container}:{CONTAINER_Q}"]),
            ("cp", ["cp", str(WORKER), f"{args.container}:{CONTAINER_WORKER}"]),
            (
                "exec",
                [
                    "exec",
                    "-w",
                    "/app",
                    "-e",
                    "PYTHONPATH=/app",
                    args.container,
                    "python",
                    CONTAINER_WORKER,
                    "--questions",
                    CONTAINER_Q,
                    "--out",
                    CONTAINER_REPORT,
                ],
            ),
            (
                "cp",
                [
                    "cp",
                    f"{args.container}:{CONTAINER_REPORT}",
                    str(Path(td) / "report.json"),
                ],
            ),
        ]
        for label, cmd_args in steps:
            proc = docker(*cmd_args, capture=True)
            if proc.returncode != 0:
                print(f"[FAIL] docker {label}: {proc.stderr.strip()}", file=sys.stderr)
                return 1
            if label == "exec" and proc.stdout.strip():
                print(proc.stdout.strip())

        report = json.loads((Path(td) / "report.json").read_text(encoding="utf-8"))

    json_fp = out_dir / f"retrieval_{stamp}.json"
    md_fp = out_dir / f"retrieval_{stamp}.md"
    json_fp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_fp.write_text(render_markdown(report), encoding="utf-8")

    print(f"JSON 报告：{json_fp}")
    print(f"Markdown 报告：{md_fp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
