#!/usr/bin/env python

# ruff: noqa: S607
# S607 豁免理由：本脚本通过 subprocess 调用 docker CLI 读取容器状态
# （如 `docker ps`、`docker inspect`、`docker exec`）。命令名与容器名
# 全部在本文件内硬编码，不来自任何外部输入，且以列表形式传参、
# 不经过 shell，故「部分可执行路径」的风险不成立。
"""知识库 RAG 全链路验证脚本（接口 + 向量 + 聊天引用）

覆盖的验收链路：
    登录 → 建知识库 → 上传 PDF/DOCX/TXT/MD → 查文档列表
    → 命中测试 → Chroma 向量数核对 → WebSocket 聊天 → 校验引用来源

设计要点：
    1. 素材里埋了「独有事实」（如 187 摄氏度），模型不可能凭空知道，
       因此只要回复或引用里出现该事实，就能判定检索真的生效，而不是模型瞎编。
    2. 四种格式故意用不同的独有数字，用来判断命中的究竟是哪一份文档，
       从而验证引用溯源是否精确（而非串台到别的文档）。
    3. 退出码 0 表示全部断言通过，非 0 表示存在失败项，便于 CI / 人工判断。

用法：
    python scripts/verify_knowledge_rag.py
    python scripts/verify_knowledge_rag.py \
        --container prod-app-1 --report /tmp/kb_rag_report.json
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import uuid
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 测试常量：独有事实 → 用于判定检索是否真的生效
# ---------------------------------------------------------------------------
# 每份素材埋一个独有的数值事实，互不重复，便于判定「命中了哪份文档」。
FIXTURES = [
    {
        "file": "kb_md_manual.md",
        "format": "md",
        "expect_hit_keyword": "187",  # 腔体预热温度 187 摄氏度
        "question": "XG-9000 的腔体预热温度是多少摄氏度，需要预热多久？",
    },
    {
        "file": "kb_txt_note.txt",
        "format": "txt",
        # 交接编号只在纯文本素材里出现，是四份素材中唯一的，用它判定命中来源最可靠
        # （早先用的 TC-K-32 在 docx 素材里也有，命中会被误判为「来自 txt」）。
        "expect_hit_keyword": "XO-2026-0912",
        "question": "现场调试交接记录的交接编号是什么？",
    },
    {
        "file": "kb_docx_upgrade.docx",
        "format": "docx",
        "expect_hit_keyword": "192",  # V3 固件后的预热温度 192 摄氏度
        "question": "V3 固件升级后，腔体预热温度调整为多少摄氏度？",
    },
    {
        "file": "kb_pdf_safety.pdf",
        "format": "pdf",
        "expect_hit_keyword": "74",  # 腔体外壁最高温度 74 摄氏度
        "question": "安全操作规范里，腔体预热期间外壁最高温度能达到多少摄氏度？",
    },
]


class Reporter:
    """收集每一步的结果，最后统一输出 JSON 报告"""

    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.failures: list[str] = []

    def add(self, name: str, ok: bool, detail: dict) -> None:
        self.steps.append({"step": name, "ok": ok, "detail": detail})
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}")
        if not ok:
            self.failures.append(name)

    def check(self, cond: bool, name: str, detail: dict) -> bool:
        self.add(name, bool(cond), detail)
        return bool(cond)


def login(base: str, user: str, password: str) -> str:
    """登录获取 JWT"""
    r = requests.post(
        f"{base}/api/v1/auth/login",
        json={"username": user, "password": password},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("token") or data.get("access_token") or ""
    if not token:
        raise RuntimeError(f"登录响应中没有 token: {data}")
    return token


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_kb(base: str, token: str, name: str) -> dict:
    r = requests.post(
        f"{base}/api/v1/admin/knowledge",
        headers=auth_headers(token),
        json={"name": name, "description": "RAG 全链路验证用知识库"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["kb"]


def upload_document(base: str, token: str, kb_id: str, path: Path) -> dict:
    """multipart 上传单个文档"""
    with open(path, "rb") as f:
        r = requests.post(
            f"{base}/api/v1/admin/knowledge/{kb_id}/documents/upload",
            headers=auth_headers(token),
            files={"file": (path.name, f, "application/octet-stream")},
            timeout=180,
        )
    body = None
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    return {"status_code": r.status_code, "body": body}


def list_documents(base: str, token: str, kb_id: str) -> dict:
    r = requests.get(
        f"{base}/api/v1/admin/knowledge/{kb_id}/documents",
        headers=auth_headers(token),
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def hit_test(base: str, token: str, kb_id: str, query: str, top_k: int = 3) -> dict:
    r = requests.post(
        f"{base}/api/v1/admin/knowledge/{kb_id}/hit_test",
        headers=auth_headers(token),
        json={"query": query, "top_k": top_k},
        timeout=120,
    )
    body = None
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    return {"status_code": r.status_code, "body": body}


def ws_chat(ws_url: str, question: str, timeout: float = 150.0) -> dict:
    """通过 WebSocket 发一条聊天消息，收集流式分片与最终引用

    返回 dict：answer 文本、citations 列表、原始消息类型序列。

    实现要点（为什么要用后台线程 + 硬超时）：
        服务端在长耗时推理期间可能长时间不推帧，也可能走到「转人工」分支而
        根本不发 done 帧。此时 socket 层的 recv / close 都可能长时间阻塞，
        仅靠循环里的时间判断兜不住（实测等待时间会远超设定上限）。
        因此把收发逻辑放进 daemon 线程，主线程只 join 一个硬上限；
        超时就带着「已经收到的部分」返回，保证脚本一定继续往下走。
    """
    import threading

    import websocket  # websocket-client

    session_id = str(uuid.uuid4())
    box: dict = {"answer": "", "citations": [], "msg_types": [], "done": False}

    def _worker() -> None:
        answer_parts: list[str] = []
        try:
            ws = websocket.create_connection(f"{ws_url}?token={ws_token}", timeout=10)
            with contextlib.suppress(Exception):
                # 部分实现不支持 settimeout，设不上不影响后续收发
                ws.settimeout(10)
            try:
                ws.send(
                    json.dumps(
                        {
                            "type": "chat_message",
                            "message": question,
                            "session_id": session_id,
                        }
                    )
                )
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    except Exception:
                        # 连接被服务端关闭 / 其它 socket 错误：停止收帧，
                        # 已收到的内容仍然有效
                        break
                    if not raw:
                        continue
                    try:
                        msg = json.loads(raw)
                    except Exception:  # noqa: S112 —— 非JSON 帧属预期，跳过
                        # 非 JSON 帧（心跳/心跳确认等）跳过
                        continue  # noqa: S112
                    mtype = msg.get("type", "")
                    box["msg_types"].append(mtype)
                    if mtype == "streaming_chunk":
                        text = msg.get("text") or msg.get("delta") or ""
                        if text:
                            answer_parts.append(text)
                        if msg.get("citations"):
                            box["citations"] = msg["citations"]
                        if msg.get("done"):
                            box["done"] = True
                            break
                    elif mtype == "error":
                        answer_parts.append(f"[ERROR] {msg.get('message')}")
                        box["done"] = True
                        break
            finally:
                with contextlib.suppress(Exception):
                    # 收尾清理，连接可能已被对端关闭
                    ws.settimeout(2)
                    ws.close()
        finally:
            # 无论正常结束还是超时被放弃，都在这里落盘已收到的内容
            box["answer"] = "".join(answer_parts)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout + 10)  # 硬上限：比 socket 循环的预算多给 10 秒收尾

    return {
        "question": question,
        "answer": box["answer"],
        "citations": box["citations"] or [],
        "message_types": box["msg_types"][:40],
        "done_received": box["done"],
        "worker_finished": not t.is_alive(),
    }


ws_token = ""  # 由 main 注入（websocket-client 无法设自定义头，改用 query 传参）


def probe_chroma(container: str) -> dict:
    """容器内直查 ChromaDB，核对向量是否真的落盘"""
    import subprocess

    py = (
        "import sqlite3,json;"
        "c=sqlite3.connect('/app/chroma_data/chroma.sqlite3');cur=c.cursor();"
        "cur.execute('select count(*) from embeddings');n=cur.fetchone()[0];"
        'cur.execute("select name from collections");'
        "cols=[r[0] for r in cur.fetchall()];"
        'cur.execute("select key,count(*) from embedding_metadata"'
        ' " group by key order by 2 desc");'
        "keys=cur.fetchall();"
        "print(json.dumps({'embeddings':n,'collections':cols,"
        "'metadata_keys':keys},ensure_ascii=False))"
    )
    try:
        # S603：container 由本脚本调用方指定（固定容器名），py 是上面
        # 本地拼出的常量字符串，均不来自网络或其他不可信输入
        out = subprocess.run(  # noqa: S603 —— 容器名与内联脚本均本地硬编码，不接受外部输入
            ["docker", "exec", container, "python", "-c", py],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if out.returncode != 0:
            return {"error": out.stderr.strip()[:300]}
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"error": str(e)[:300]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000", help="API 基址")
    ap.add_argument("--ws-url", default="ws://localhost:8000/ws/chat", help="WS 端点")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin123")
    ap.add_argument("--fixtures-dir", default="fixtures/kb_test")
    ap.add_argument("--container", default="", help="app 容器名，给了才做 Chroma 直查")
    ap.add_argument("--report", default="", help="JSON 报告输出路径")
    ap.add_argument(
        "--skip-ws", action="store_true", help="跳过聊天验证（仅测 API+向量）"
    )
    ap.add_argument(
        "--ws-limit",
        type=int,
        default=1,
        help=(
            "聊天验证用几个问题（默认 1）。"
            "内网 7B 模型在 CPU 上每轮 ReAct 要 1~3 分钟，四种格式全走一遍聊天"
            "会拖到十几分钟；聊天链路本身与文档格式无关（检索层统一处理 chunk），"
            "因此默认只验证 1 个问题即可证明链路通，其余格式的检索由 hit_test 覆盖。"
        ),
    )
    ap.add_argument(
        "--ws-timeout",
        type=float,
        default=150.0,
        help=(
            "单个聊天问题的等待上限（秒）。服务端在长推理期间可能长时间不推帧，"
            "也可能走到「转人工」分支而不发 done 帧，因此必须有硬上限；"
            "超时不算失败，脚本会记录实际收到的帧类型序列。"
        ),
    )
    args = ap.parse_args()

    global ws_token
    base = args.base.rstrip("/")
    fixtures_dir = Path(args.fixtures_dir)
    rep = Reporter()

    print("=" * 72)
    print("知识库 RAG 全链路验证")
    print("=" * 72)

    # ---- 0. 健康检查 ----
    print("\n[0] 服务健康检查")
    try:
        h = requests.get(f"{base}/api/v1/health", timeout=15)
        rep.check(
            h.status_code == 200,
            "GET /api/v1/health",
            {
                "status_code": h.status_code,
                "body": h.json(),
            },
        )
    except Exception as e:
        rep.check(False, "GET /api/v1/health", {"error": str(e)})
        return _finish(rep, args.report)

    # ---- 1. 登录 ----
    print("\n[1] 登录获取 token")
    try:
        token = login(base, args.user, args.password)
        ws_token = token
        rep.check(
            bool(token),
            "POST /api/v1/auth/login",
            {
                "username": args.user,
                "token_prefix": token[:24] + "...",
            },
        )
    except Exception as e:
        rep.check(False, "POST /api/v1/auth/login", {"error": str(e)})
        return _finish(rep, args.report)

    # ---- 2. 创建知识库 ----
    print("\n[2] 创建知识库")
    kb_name = f"RAG验证库-{time.strftime('%m%d-%H%M%S')}"
    try:
        kb = create_kb(base, token, kb_name)
        kb_id = kb["id"]
        rep.check(
            bool(kb_id),
            "POST /api/v1/admin/knowledge",
            {
                "kb_id": kb_id,
                "name": kb_name,
            },
        )
    except Exception as e:
        rep.check(False, "POST /api/v1/admin/knowledge", {"error": str(e)})
        return _finish(rep, args.report)

    # ---- 3. 上传四种格式 ----
    print("\n[3] 上传文档（MD / TXT / DOCX / PDF）")
    uploaded: dict[str, dict] = {}
    for fx in FIXTURES:
        path = fixtures_dir / fx["file"]
        if not path.exists():
            rep.check(False, f"上传 {fx['file']}", {"error": "素材文件不存在"})
            continue
        res = upload_document(base, token, kb_id, path)
        body = res["body"] or {}
        doc = body.get("document") or {}
        uploaded[fx["format"]] = doc
        ok = res["status_code"] == 200 and doc.get("id")
        rep.check(
            ok,
            f"上传 {fx['file']}",
            {
                "status_code": res["status_code"],
                "doc_id": doc.get("id"),
                "doc_format": doc.get("doc_format"),
                "chunk_count": doc.get("chunk_count"),
                "status": doc.get("status"),
                "file_size": doc.get("file_size"),
            },
        )

    # 每种格式都必须产出 chunk（chunk_count > 0），否则等于没入库
    for fx in FIXTURES:
        doc = uploaded.get(fx["format"]) or {}
        rep.check(
            (doc.get("chunk_count") or 0) > 0,
            f"{fx['format'].upper()} 产出切片数 > 0",
            {"chunk_count": doc.get("chunk_count")},
        )

    # ---- 4. 文档列表 ----
    print("\n[4] 查询文档列表")
    try:
        docs_resp = list_documents(base, token, kb_id)
        total = docs_resp.get("total", 0)
        rep.check(
            total >= len(FIXTURES),
            "GET .../documents",
            {
                "total": total,
                "formats": sorted(
                    {d.get("doc_format") for d in docs_resp.get("documents", [])}
                ),
            },
        )
    except Exception as e:
        rep.check(False, "GET .../documents", {"error": str(e)})

    # ---- 5. 命中测试 ----
    print("\n[5] 命中测试（hit_test）")
    hit_results: dict[str, dict] = {}
    for fx in FIXTURES:
        res = hit_test(base, token, kb_id, fx["question"])
        body = res["body"] or {}
        hits = body.get("hits") or []
        joined = " ".join(h.get("content", "") for h in hits)
        hit_ok = fx["expect_hit_keyword"] in joined
        hit_results[fx["format"]] = {
            "status_code": res["status_code"],
            "total_hits": body.get("total_hits"),
            "keyword_expected": fx["expect_hit_keyword"],
            "keyword_found": hit_ok,
            "top_hit_source": (hits[0].get("source") if hits else None),
            "top_hit_score": (hits[0].get("score") if hits else None),
            "top_hit_preview": (hits[0].get("content", "")[:120] if hits else ""),
        }
        rep.check(
            hit_ok and len(hits) > 0,
            f"hit_test 命中 {fx['format'].upper()} 独有事实",
            hit_results[fx["format"]],
        )

    # ---- 6. Chroma 向量直查 ----
    chroma = {}
    if args.container:
        print("\n[6] 容器内 ChromaDB 向量核对")
        chroma = probe_chroma(args.container)
        n = chroma.get("embeddings", 0)
        rep.check(isinstance(n, int) and n > 0, "Chroma embeddings 行数 > 0", chroma)
    else:
        print("\n[6] 跳过 Chroma 直查（未指定 --container）")

    # ---- 7. 聊天引用验证 ----
    chat_results = []
    if not args.skip_ws:
        print(f"\n[7] WebSocket 聊天引用验证（最多 {args.ws_limit} 个问题）")
        for fx in FIXTURES[: max(0, args.ws_limit)]:
            try:
                res = ws_chat(args.ws_url, fx["question"], timeout=args.ws_timeout)
                answer = res["answer"]
                cites = res["citations"]
                cite_text = (
                    " ".join(
                        (c.get("content") or "") + " " + (c.get("title") or "")
                        for c in cites
                    )
                    if isinstance(cites, list)
                    else ""
                )
                keyword_ok = (
                    fx["expect_hit_keyword"] in answer
                    or fx["expect_hit_keyword"] in cite_text
                )
                has_cites = bool(cites)
                chat_results.append(
                    {
                        "format": fx["format"],
                        "question": fx["question"],
                        "answer": answer[:600],
                        "citation_count": len(cites) if isinstance(cites, list) else 0,
                        "citations": [
                            {
                                "title": c.get("title"),
                                "doc_id": c.get("doc_id"),
                                "kb_id": c.get("kb_id"),
                                "score": c.get("score"),
                                "content_preview": (c.get("content") or "")[:120],
                            }
                            for c in (cites if isinstance(cites, list) else [])
                        ][:3],
                        "keyword_expected": fx["expect_hit_keyword"],
                        "keyword_found": keyword_ok,
                        "done_received": res["done_received"],
                    }
                )
                rep.check(
                    has_cites and keyword_ok,
                    f"聊天引用命中 {fx['format'].upper()} 独有事实",
                    chat_results[-1],
                )
            except Exception as e:
                chat_results.append({"format": fx["format"], "error": str(e)[:300]})
                rep.check(
                    False,
                    f"聊天引用命中 {fx['format'].upper()} 独有事实",
                    {"error": str(e)[:300]},
                )
    else:
        print("\n[7] 跳过聊天验证（--skip-ws）")

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": base,
        "kb": {"id": kb_id, "name": kb_name},
        "fixtures": [fx["file"] for fx in FIXTURES],
        "uploaded_documents": uploaded,
        "hit_test": hit_results,
        "chroma": chroma,
        "chat": chat_results,
        "steps": rep.steps,
        "failures": rep.failures,
        "summary": {
            "total_checks": len(rep.steps),
            "passed": sum(1 for s in rep.steps if s["ok"]),
            "failed": len(rep.failures),
        },
    }
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return _finish(rep, args.report, report)


def _finish(rep: Reporter, report_path: str, report: dict | None = None) -> int:
    print("\n" + "=" * 72)
    passed = sum(1 for s in rep.steps if s["ok"])
    print(f"结果：{passed}/{len(rep.steps)} 项通过")
    if rep.failures:
        print("失败项：")
        for f in rep.failures:
            print(f"  - {f}")
    if report_path:
        print(f"报告已写入：{report_path}")
    print("=" * 72)
    return 0 if not rep.failures else 1


if __name__ == "__main__":
    sys.exit(main())
