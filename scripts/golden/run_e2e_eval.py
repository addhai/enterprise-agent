#!/usr/bin/env python3
"""金标题库端到端判分器（真实 WS 问答 + 自动判分 + 人工复核位）。

链路与生产冒烟同构：POST /api/v1/auth/login 取 token -> 每题新建 WS
会话 /ws/chat -> 收 streaming_chunk 至 done -> 按题库判分。

判分规则（与 tests/golden/questions.yaml 头注释对齐）：
  普通题   answer.keyword_groups 外层 AND、组内 OR，归一化去空白后子串匹配
  拒答题   refusal.hedge_any 命中任一；topic_any 非空时还需命中任一
  自动结论仅作参考，rows[].human_verdict 留空给人工复核后填写

工程约束：
  CPU 单题 130~220s，WS 单实例 BUSY 语义，全程严格串行
  每题落盘一次（崩溃不丢已跑结果），--resume 可续跑 pass/fail 之外的题

产物：
  scripts/golden/reports/e2e_<时间戳>.json  逐题完整答案与明细
  scripts/golden/reports/e2e_<时间戳>.md    汇总+失题清单
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import httpx
import websockets
import yaml

# 题库 2026-10-08 起冻结：评测前强制校验内容锁，锁失配直接退出
from bank_lock import ensure_frozen_or_exit

WS_TIMEOUT_S = 600.0  # 与生产 600s 墙钟硬超时对齐
READY_TIMEOUT_S = 15.0
GAP_S = 5.0  # 题间间隔，避开在途问答 BUSY

VERDICT_TERMINAL = ("pass", "fail")


def norm(text: str) -> str:
    """归一化：去全部空白（含全角空格）并小写化，便于数字/英文关键词匹配。"""
    return re.sub(r"\s+", "", text).replace("　", "").casefold()


def match_keyword_groups(answer: str, groups: list[list[str]]) -> list[dict]:
    """外层 AND 组内 OR，逐组返回命中词与缺失组。"""
    haystack = norm(answer)
    details = []
    for group in groups:
        hit = next((kw for kw in group if norm(kw) in haystack), None)
        details.append({"options": group, "matched": hit})
    return details


def percentile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    ordered = sorted(xs)
    k = (len(ordered) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


def login(base_url: str, user: str, password: str) -> str:
    r = httpx.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": user, "password": password},
        timeout=15,
    )
    r.raise_for_status()
    token = r.json().get("token")
    if not token:
        raise RuntimeError("登录响应无 token")
    return token


async def ask_once(ws_base: str, token: str, question: str, timeout: float) -> dict:
    """单题单会话问答，返回原始观测（不含判分）。"""
    obs: dict = {
        "session_id": None,
        "answer": "",
        "first_token_s": None,
        "elapsed_s": None,
        "frames": [],
        "citations": [],
        "suggest_human": False,
        "status": "ok",  # ok / busy / error / timeout
        "error": None,
    }
    t0 = time.perf_counter()
    async with websockets.connect(
        f"{ws_base}/ws/chat?token={token}",
        open_timeout=READY_TIMEOUT_S,
        max_size=4 * 1024 * 1024,
        # 直答路径一次 LLM 调用可达 200-450s，期间无任何业务帧。
        # websockets 默认 20s ping/20s pong 超时会在长推理静默期主动掐断
        # （A 轮 GF13/GP10、11 题样本 GS12 均零帧 ConnectionClosedError，
        #  服务端 LLM 实际 200 正常返回）。关闭客户端心跳，存活性交给
        # ws-timeout(900s) 与服务端硬超时兜底。与 verify_pdf_page_citation.py
        # 的既有写法保持一致。
        ping_interval=None,
        ping_timeout=None,
    ) as ws:
        ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=READY_TIMEOUT_S))
        obs["session_id"] = ready.get("session_id")
        await ws.send(json.dumps({"type": "chat_message", "message": question}))

        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            frame = json.loads(raw)
            ftype = frame.get("type")
            obs["frames"].append(ftype)
            if ftype == "busy":
                obs["status"] = "busy"
                obs["error"] = "服务忙（BUSY），有另一个在途问答"
                break
            if ftype == "error":
                obs["status"] = "error"
                obs["error"] = frame.get("message") or json.dumps(
                    frame, ensure_ascii=False
                )
                break
            if ftype == "streaming_chunk":
                text = frame.get("text") or ""
                if text and obs["first_token_s"] is None:
                    obs["first_token_s"] = round(time.perf_counter() - t0, 1)
                obs["answer"] += text
                if frame.get("suggest_human"):
                    obs["suggest_human"] = True
                if frame.get("done"):
                    obs["citations"] = frame.get("citations") or []
                    break
    obs["elapsed_s"] = round(time.perf_counter() - t0, 1)
    return obs


def judge(question: dict, obs: dict) -> dict:
    """把原始观测判成自动结论。"""
    row: dict = {
        "id": question["id"],
        "type": question["type"],
        "difficulty": question.get("difficulty"),
        "question": question["question"],
        "session_id": obs.get("session_id"),
        "elapsed_s": obs.get("elapsed_s"),
        "first_token_s": obs.get("first_token_s"),
        "answer_len": len((obs.get("answer") or "").strip()),
        "answer": obs.get("answer") or "",
        "citation_count": len(obs.get("citations") or []),
        "citation_sources": [
            c.get("source") for c in (obs.get("citations") or []) if isinstance(c, dict)
        ],
        "citation_pages": [
            c.get("page")
            for c in (obs.get("citations") or [])
            if isinstance(c, dict) and c.get("page")
        ],
        "suggest_human": obs.get("suggest_human", False),
        "frames": obs.get("frames"),
        "human_verdict": None,  # 人工复核后填 pass/fail
        "human_note": None,
    }

    if obs["status"] == "busy":
        row["verdict"] = "busy"
        row["error"] = obs["error"]
        return row
    if obs["status"] == "error":
        row["verdict"] = "error"
        row["error"] = obs["error"]
        return row
    if obs["status"] == "timeout":
        row["verdict"] = "timeout"
        row["error"] = f"{WS_TIMEOUT_S:.0f}s 未收到 done"
        return row
    if row["answer_len"] < 10:
        row["verdict"] = "fail"
        row["error"] = f"答案过短: {row['answer'][:100]!r}"
        return row

    refusal = question.get("refusal")
    if refusal:
        hedge = refusal.get("hedge_any") or []
        topic = refusal.get("topic_any") or []
        hedge_hit = [kw for kw in hedge if norm(kw) in norm(row["answer"])]
        topic_hit = [kw for kw in topic if norm(kw) in norm(row["answer"])]
        row["refusal_match"] = {
            "hedge_hit": hedge_hit,
            "topic_hit": topic_hit,
        }
        ok = bool(hedge_hit) and (not topic or bool(topic_hit))
        row["verdict"] = "pass" if ok else "fail"
        return row

    groups = (question.get("answer") or {}).get("keyword_groups") or []
    details = match_keyword_groups(row["answer"], groups)
    missing = [d for d in details if d["matched"] is None]
    row["keyword_match"] = details
    row["missing_groups"] = [d["options"] for d in missing]
    row["verdict"] = "pass" if not missing else "fail"
    return row


async def run(args: argparse.Namespace) -> list[dict]:
    base_url = args.base_url.rstrip("/")
    ws_base = base_url.replace("http://", "ws://").replace("https://", "wss://")
    bank = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))
    ensure_frozen_or_exit(Path(args.questions))
    questions = bank["questions"]

    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[: args.limit]

    rows: dict[str, dict] = {}
    if args.resume:
        rows = load_resumable(args.out_dir)
        done = {qid for qid, r in rows.items() if r["verdict"] in VERDICT_TERMINAL}
        questions = [q for q in questions if q["id"] not in done]
        print(
            f"[resume] 已完成 {len(done)} 题，本次续跑 {len(questions)} 题", flush=True
        )

    if not questions:
        print("没有待跑题目", flush=True)
        return list(rows.values())

    token = login(base_url, args.user, args.password)
    print(f"登录成功，开始串行评测 {len(questions)} 题", flush=True)

    for i, q in enumerate(questions, start=1):
        print(f"[{i}/{len(questions)}] {q['id']} {q['question'][:40]}", flush=True)
        row = None
        for attempt in (1, 2):  # BUSY 时最多等 60s 重试一次
            try:
                obs = await ask_once(ws_base, token, q["question"], args.ws_timeout)
            except asyncio.TimeoutError:
                obs = {"status": "timeout", "answer": "", "error": None}
            except Exception as e:  # noqa: BLE001 - 连接级异常单题隔离
                obs = {
                    "status": "error",
                    "answer": "",
                    "error": f"{type(e).__name__}: {e}",
                }
            # 补全 ask_once 的默认字段，异常路径下字典是精简版
            obs.setdefault("session_id", None)
            obs.setdefault("answer", "")
            obs.setdefault("first_token_s", None)
            obs.setdefault("elapsed_s", None)
            obs.setdefault("frames", [])
            obs.setdefault("citations", [])
            obs.setdefault("suggest_human", False)
            row = judge(q, obs)
            if row["verdict"] != "busy" or attempt == 2:
                break
            print("  BUSY，60s 后重试", flush=True)
            await asyncio.sleep(60)

        rows[row["id"]] = row
        preview = row["answer"].replace("\n", " ")[:120]
        print(
            f"  -> {row['verdict']} {row['elapsed_s']}s "
            f"引用{row['citation_count']}条 | {preview}",
            flush=True,
        )
        # 每题落盘，长测崩溃不丢结果
        save_reports(
            args.out_dir, bank.get("meta") or {}, list(rows.values()), stamp=args.stamp
        )
        if i < len(questions):
            await asyncio.sleep(args.gap)

    return list(rows.values())


def load_resumable(out_dir: str) -> dict[str, dict]:
    d = Path(out_dir)
    candidates = sorted(d.glob("e2e_*.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return {}
    data = json.loads(candidates[-1].read_text(encoding="utf-8"))
    return {r["id"]: r for r in data.get("rows", [])}


def summarize(rows: list[dict]) -> dict:
    by_type: dict[str, dict] = {}
    for r in rows:
        b = by_type.setdefault(
            r["type"],
            {"total": 0, "pass": 0, "fail": 0, "error": 0, "busy": 0, "timeout": 0},
        )
        b["total"] += 1
        b[r["verdict"]] = b.get(r["verdict"], 0) + 1

    lat = [r["elapsed_s"] for r in rows if r.get("elapsed_s")]
    ttf = [r["first_token_s"] for r in rows if r.get("first_token_s")]
    return {
        "total": len(rows),
        "pass": sum(1 for r in rows if r["verdict"] == "pass"),
        "by_type": by_type,
        "latency_s": {
            "avg": round(sum(lat) / len(lat), 1) if lat else None,
            "p50": percentile(lat, 0.5),
            "p95": percentile(lat, 0.95),
            "max": max(lat) if lat else None,
        },
        "first_token_s": {
            "avg": round(sum(ttf) / len(ttf), 1) if ttf else None,
            "p50": percentile(ttf, 0.5),
            "p95": percentile(ttf, 0.95),
        },
        "suggest_human": sum(1 for r in rows if r.get("suggest_human")),
    }


def render_markdown(meta: dict, rows: list[dict]) -> str:
    s = summarize(rows)
    lines = [
        "# 金标题库端到端评测报告",
        "",
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 题数：{s['total']}，自动判定通过：**{s['pass']}**"
        f"（{round(100 * s['pass'] / s['total'], 1) if s['total'] else 0}%）",
        f"- 端到端耗时：avg {s['latency_s']['avg']}s，p50 {s['latency_s']['p50']}s，"
        f"p95 {s['latency_s']['p95']}s，max {s['latency_s']['max']}s",
        f"- 首 token：avg {s['first_token_s']['avg']}s，"
        f"p50 {s['first_token_s']['p50']}s，p95 {s['first_token_s']['p95']}s",
        f"- 建议转人工次数：{s['suggest_human']}",
        "- 自动结论仅作筛选，所有 fail/error 题需人工复核 human_verdict",
        "",
        "## 分类型指标",
        "",
        "| 类型 | 题数 | pass | fail | error | busy | timeout |",
        "|------|------|------|------|-------|------|---------|",
    ]
    name = {
        "fact": "事实定位",
        "synthesis": "跨章综合",
        "procedure": "操作流程",
        "refusal": "拒答越界",
    }
    for t in ("fact", "synthesis", "procedure", "refusal"):
        b = s["by_type"].get(t)
        if not b:
            continue
        lines.append(
            f"| {name[t]} | {b['total']} | {b['pass']} | {b['fail']} | "
            f"{b.get('error', 0)} | {b.get('busy', 0)} | {b.get('timeout', 0)} |"
        )

    bad = [r for r in rows if r["verdict"] != "pass"]
    lines += ["", f"## 未通过题清单（{len(bad)} 题，待人工复核）", ""]
    for r in bad:
        lines.append(f"### {r['id']} [{r['type']}] {r['verdict']}")
        lines.append(f"- 问：{r['question']}")
        if r.get("error"):
            lines.append(f"- 异常：{r['error']}")
        if r.get("missing_groups"):
            lines.append(f"- 缺词组：{r['missing_groups']}")
        rm = r.get("refusal_match")
        if rm:
            lines.append(
                f"- 拒答信号：hedge {rm['hedge_hit']}，topic {rm['topic_hit']}"
            )
        lines.append(
            f"- 耗时 {r.get('elapsed_s')}s，引用 {r.get('citation_count')} 条 "
            f"{r.get('citation_sources')}"
        )
        preview = (r.get("answer") or "").replace("\n", " ")[:400]
        lines.append(f"- 答案前 400 字：{preview}")
        lines.append("")
    return "\n".join(lines)


def save_reports(out_dir: str, meta: dict, rows: list[dict], stamp: str) -> None:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "bank_meta": meta,
        "summary": summarize(rows),
        "rows": rows,
    }
    (d / f"e2e_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (d / f"e2e_{stamp}.md").write_text(render_markdown(meta, rows), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="金标题库端到端评测")
    ap.add_argument("--questions", default="tests/golden/questions.yaml")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--user", default="smoke_kbmode")
    ap.add_argument("--password", default="Smoke#20261005")
    ap.add_argument("--ids", help="逗号分隔的题号白名单，如 GF02,GS01,GR01")
    ap.add_argument("--limit", type=int, help="只跑题库前 N 题")
    ap.add_argument("--ws-timeout", type=float, default=WS_TIMEOUT_S)
    ap.add_argument("--gap", type=float, default=GAP_S, help="题间间隔秒")
    ap.add_argument("--out-dir", default="scripts/golden/reports")
    ap.add_argument("--resume", action="store_true", help="续跑目录内最近一次报告")
    args = ap.parse_args()
    args.stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.resume:
        # 续跑沿用旧文件名，保持一份完整报告
        d = Path(args.out_dir)
        olds = sorted(d.glob("e2e_*.json"), key=lambda p: p.stat().st_mtime)
        if olds:
            args.stamp = olds[-1].stem.removeprefix("e2e_")

    rows = asyncio.run(run(args))
    if not rows:
        return 1
    bank = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))
    save_reports(args.out_dir, bank.get("meta") or {}, rows, stamp=args.stamp)
    s = summarize(rows)
    print(
        f"\n===== 汇总 {s['pass']}/{s['total']} pass | "
        f"p50 {s['latency_s']['p50']}s p95 {s['latency_s']['p95']}s ====="
    )
    print(f"报告：{Path(args.out_dir) / f'e2e_{args.stamp}.md'}")
    # 自动判分不设失败门禁，人工复核前一律 0 退出，避免 CI 误判
    return 0


if __name__ == "__main__":
    sys.exit(main())
