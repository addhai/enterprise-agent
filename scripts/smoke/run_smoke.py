#!/usr/bin/env python3
"""生产冒烟测试（发布门禁 + 重建验收）。

覆盖链路:
  S1 轻量探针    GET  /api/v1/health          （Docker 探针同路径）
  S2 依赖明细    GET  /api/v1/health/detail    （旧镜像 404 自动降级 WARN）
  S3 登录鉴权    POST /api/v1/auth/login
  S4 WS 建连     /ws/chat?token=... 等 ready
  S5 工业问答    F02 已知答案题，校验答案关键词、引用数、页码字段
  S6 引用结构    title/source/score/page 四字段齐全

退出码: 0 全部 PASS/WARN；1 存在 FAIL 或脚本自身异常。
报告: 控制台逐条结果 + scripts/smoke/reports/smoke_<label>_<时间戳>.json

用法:
  python scripts/smoke/run_smoke.py --label pre
  python scripts/smoke/run_smoke.py --label post --require-page
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import time

import httpx
import websockets

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

# 单题 CPU 推理历史耗时 130~200s，重建/冷启动后留足余量
DEFAULT_WS_TIMEOUT = 480


class Report:
    def __init__(self, label: str, base_url: str):
        self.label = label
        self.base_url = base_url
        self.started = dt.datetime.now().isoformat(timespec="seconds")
        self.items: list[dict] = []

    def add(self, sid: str, name: str, status: str, detail: str, **metrics) -> None:
        item = {"id": sid, "name": name, "status": status, "detail": detail}
        item.update(metrics)
        self.items.append(item)
        line = f"[{status}] {sid} {name} - {detail}"
        if metrics.get("elapsed_s") is not None:
            line += f" ({metrics['elapsed_s']:.1f}s)"
        print(line, flush=True)

    @property
    def has_fail(self) -> bool:
        return any(i["status"] == FAIL for i in self.items)

    def save(self, out_dir: str) -> str:
        from pathlib import Path

        path = Path(out_dir)
        path.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        fp = path / f"smoke_{self.label}_{stamp}.json"
        payload = {
            "label": self.label,
            "base_url": self.base_url,
            "started": self.started,
            "finished": dt.datetime.now().isoformat(timespec="seconds"),
            "result": FAIL if self.has_fail else PASS,
            "items": self.items,
        }
        fp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(fp)


def check_health(client: httpx.Client, rep: Report) -> None:
    t0 = time.perf_counter()
    try:
        r = client.get("/api/v1/health", timeout=10)
        elapsed = time.perf_counter() - t0
        if r.status_code != 200:
            rep.add("S1", "轻量探针", FAIL, f"HTTP {r.status_code}", elapsed_s=elapsed)
            return
        body = r.json()
        if body.get("status") != "ok":
            rep.add(
                "S1",
                "轻量探针",
                FAIL,
                f"body.status={body.get('status')}",
                elapsed_s=elapsed,
            )
            return
        rep.add(
            "S1",
            "轻量探针",
            PASS,
            f"status=ok fallback={body.get('aliyun_demo_fallback')}",
            elapsed_s=elapsed,
        )
    except Exception as e:
        rep.add("S1", "轻量探针", FAIL, f"异常 {type(e).__name__}: {e}")


def check_detail(client: httpx.Client, rep: Report) -> dict | None:
    t0 = time.perf_counter()
    try:
        r = client.get("/api/v1/health/detail", timeout=15)
        elapsed = time.perf_counter() - t0
    except Exception as e:
        rep.add("S2", "依赖明细", FAIL, f"请求异常 {type(e).__name__}: {e}")
        return None
    if r.status_code == 404:
        rep.add(
            "S2",
            "依赖明细",
            WARN,
            "404 旧镜像无此端点（重建后应消失）",
            elapsed_s=time.perf_counter() - t0,
        )
        return None
    if r.status_code != 200:
        rep.add("S2", "依赖明细", FAIL, f"HTTP {r.status_code}")
        return None
    body = r.json()
    checks = body.get("checks", {})
    problems = []
    warnings = []
    if checks.get("database") != "ok":
        problems.append(f"database={checks.get('database')}")
    if checks.get("vector_store") == "down":
        problems.append("vector_store=down")
    elif checks.get("vector_store") == "empty":
        warnings.append("vector_store=empty")
    if checks.get("ollama") != "ok":
        problems.append(f"ollama={checks.get('ollama')}")
    if checks.get("models") == "partial":
        warnings.append("models=partial（仅一个模型就绪）")
    elif checks.get("models") == "none":
        problems.append("models=none")
    detail = (
        f"overall={body.get('status')} checks={json.dumps(checks, ensure_ascii=False)}"
    )
    status = FAIL if problems else (WARN if warnings else PASS)
    if problems or warnings:
        detail += " | " + ";".join(problems + warnings)
    rep.add("S2", "依赖明细", status, detail, elapsed_s=elapsed)
    return checks


def login(client: httpx.Client, rep: Report, user: str, password: str) -> str | None:
    t0 = time.perf_counter()
    try:
        r = client.post(
            "/api/v1/auth/login",
            json={"username": user, "password": password},
            timeout=15,
        )
        elapsed = time.perf_counter() - t0
    except Exception as e:
        rep.add("S3", "登录鉴权", FAIL, f"请求异常 {type(e).__name__}: {e}")
        return None
    if r.status_code != 200:
        rep.add(
            "S3",
            "登录鉴权",
            FAIL,
            f"HTTP {r.status_code} {r.text[:120]}",
            elapsed_s=elapsed,
        )
        return None
    token = r.json().get("token")
    if not token:
        rep.add("S3", "登录鉴权", FAIL, "响应无 token 字段", elapsed_s=elapsed)
        return None
    rep.add("S3", "登录鉴权", PASS, f"用户 {user} 取到 token", elapsed_s=elapsed)
    return token


async def ws_roundtrip(
    ws_base: str,
    token: str,
    question: str,
    keywords: list[str],
    timeout: float,
    require_page: bool,
) -> dict:
    """完整 WS 问答，返回结构化结果（不在此函数内判级）"""
    result: dict = {
        "session_id": None,
        "answer": "",
        "elapsed_s": None,
        "frames": [],
        "citations": [],
        "error": None,
        "busy": False,
    }
    t0 = time.perf_counter()
    async with websockets.connect(
        f"{ws_base}/ws/chat?token={token}", open_timeout=15, max_size=4 * 1024 * 1024
    ) as ws:
        ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        result["session_id"] = ready.get("session_id")
        await ws.send(json.dumps({"type": "chat_message", "message": question}))

        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            frame = json.loads(raw)
            ftype = frame.get("type")
            result["frames"].append(ftype)
            if ftype == "busy":
                result["busy"] = True
                result["error"] = "服务忙（BUSY），有另一个在途问答"
                break
            if ftype == "error":
                result["error"] = frame.get("message") or json.dumps(
                    frame, ensure_ascii=False
                )
                break
            if ftype == "streaming_chunk":
                if frame.get("text"):
                    result["answer"] += frame["text"]
                if frame.get("done"):
                    result["citations"] = frame.get("citations") or []
                    break
    result["elapsed_s"] = time.perf_counter() - t0

    ans = result["answer"]
    result["answer_preview"] = ans[:300]
    result["answer_len"] = len(ans.strip())
    missing_kw = [k for k in keywords if k not in ans]
    result["missing_keywords"] = missing_kw

    paged = [c for c in result["citations"] if isinstance(c, dict) and c.get("page")]
    result["citation_count"] = len(result["citations"])
    result["paged_count"] = len(paged)
    result["page_numbers"] = [c.get("page") for c in paged]
    result["require_page"] = require_page
    return result


def judge_ws(rep: Report, res: dict, require_page: bool) -> None:
    # S4 建连（有 session_id 即通过）
    if res.get("session_id"):
        rep.add("S4", "WS 建连", PASS, f"session={res['session_id']}")
    else:
        rep.add("S4", "WS 建连", FAIL, res.get("error") or "未收到 ready")

    # S5 问答内容
    if res.get("busy"):
        rep.add(
            "S5",
            "工业问答",
            FAIL,
            res["error"] or "BUSY",
            elapsed_s=res.get("elapsed_s"),
        )
    elif res.get("error"):
        rep.add(
            "S5",
            "工业问答",
            FAIL,
            f"error 帧: {res['error']}",
            elapsed_s=res.get("elapsed_s"),
        )
    elif res.get("answer_len", 0) < 10:
        rep.add(
            "S5",
            "工业问答",
            FAIL,
            f"答案过短: {res.get('answer_preview')!r}",
            elapsed_s=res.get("elapsed_s"),
        )
    elif res.get("missing_keywords"):
        preview = res["answer_preview"]
        rep.add(
            "S5",
            "工业问答",
            FAIL,
            f"缺关键词 {res['missing_keywords']}，答案前 300 字: {preview}",
            elapsed_s=res.get("elapsed_s"),
            answer_len=res.get("answer_len"),
        )
    else:
        rep.add(
            "S5",
            "工业问答",
            PASS,
            f"关键词全中，答案 {res['answer_len']} 字",
            elapsed_s=res.get("elapsed_s"),
            answer_len=res.get("answer_len"),
            answer_preview=res.get("answer_preview"),
            frames=res.get("frames"),
            session_id=res.get("session_id"),
        )

    # S6 引用结构
    cites = res.get("citations") or []
    if not cites:
        rep.add("S6", "引用结构", FAIL, "done 帧无 citations")
        return
    required = ("title", "source", "score", "page")
    malformed = [
        i
        for i, c in enumerate(cites)
        if not isinstance(c, dict) or any(k not in c for k in required)
    ]
    if malformed:
        rep.add(
            "S6", "引用结构", FAIL, f"{len(malformed)} 条引用缺字段（需含 {required}）"
        )
        return
    paged = res.get("paged_count", 0)
    if require_page and paged == 0:
        rep.add(
            "S6",
            "引用结构",
            FAIL,
            f"--require-page 但 {len(cites)} 条引用页码全空（索引未含 page 戳）",
            citation_count=len(cites),
            paged_count=paged,
        )
        return
    detail = f"{len(cites)} 条引用，{paged} 条带页码 {res.get('page_numbers')}"
    status = PASS if (paged > 0 or not require_page) else WARN
    rep.add(
        "S6",
        "引用结构",
        status,
        detail,
        citation_count=len(cites),
        paged_count=paged,
        page_numbers=res.get("page_numbers"),
    )


async def run(args: argparse.Namespace) -> Report:
    base_url = args.base_url.rstrip("/")
    ws_base = base_url.replace("http://", "ws://").replace("https://", "wss://")
    rep = Report(args.label, base_url)

    with httpx.Client(base_url=base_url) as client:
        check_health(client, rep)
        check_detail(client, rep)
        token = login(client, rep, args.user, args.password)

    if not token:
        rep.add("S4", "WS 建连", FAIL, "登录失败，跳过 WS 全部检查")
        rep.add("S5", "工业问答", FAIL, "前置登录失败")
        rep.add("S6", "引用结构", FAIL, "前置登录失败")
        return rep

    try:
        res = await ws_roundtrip(
            ws_base,
            token,
            args.question,
            [k for k in args.keywords.split(",") if k.strip()],
            args.ws_timeout,
            args.require_page,
        )
        judge_ws(rep, res, args.require_page)
    except asyncio.TimeoutError:
        rep.add(
            "S5",
            "工业问答",
            FAIL,
            f"{args.ws_timeout}s 超时未收到 done（CPU 推理排队或卡死）",
            elapsed_s=float(args.ws_timeout),
        )
        rep.add("S6", "引用结构", FAIL, "问答超时，无引用")
    except Exception as e:
        rep.add("S5", "工业问答", FAIL, f"WS 异常 {type(e).__name__}: {e}")
        rep.add("S6", "引用结构", FAIL, "WS 异常")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="生产冒烟测试")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--label", default="run", help="报告文件名标签（pre/post 等）")
    ap.add_argument("--user", default="smoke_kbmode")
    ap.add_argument("--password", default="Smoke#20261005")
    ap.add_argument("--question", default="F02故障代码怎么处理？")
    ap.add_argument(
        "--keywords",
        default="快门,校正",
        help="答案必须包含的关键词，逗号分隔（F02 标准答案：快门卡滞/快门校正）",
    )
    ap.add_argument("--ws-timeout", type=float, default=DEFAULT_WS_TIMEOUT)
    ap.add_argument(
        "--require-page",
        action="store_true",
        help="重建后验收用：要求至少一条引用带非空 page",
    )
    ap.add_argument("--out-dir", default="scripts/smoke/reports")
    args = ap.parse_args()

    now_s = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"===== SMOKE [{args.label}] {args.base_url} {now_s} =====")
    print(f"题目: {args.question}")
    print(f"关键词: {args.keywords} | require_page={args.require_page}\n")

    rep = asyncio.run(run(args))
    path = rep.save(args.out_dir)

    counts = {
        s: sum(1 for i in rep.items if i["status"] == s) for s in (PASS, WARN, FAIL)
    }
    print("\n===== 汇总 =====")
    print(f"PASS={counts[PASS]} WARN={counts[WARN]} FAIL={counts[FAIL]}")
    print(f"报告: {path}")
    return 1 if rep.has_fail else 0


if __name__ == "__main__":
    sys.exit(main())
