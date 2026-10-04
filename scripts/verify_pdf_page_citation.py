"""C4 端到端验证：多页 PDF 入库后，WS 对话返回的 citations 是否带 page。

命中素材：data/docs/thermosense_t90_service_manual.pdf（7 章 7 页）
  - 问 T90 规格 → 应命中第 2 章（page=2）
  - 问 F02 故障 → 应命中第 5 章（page=5）

退出码 0 表示两个问题至少各有 1 条引用带预期页码。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

PORT = int(os.environ.get("RAG_PORT", "8000"))
BASE = f"http://127.0.0.1:{PORT}"

CASES = [
    ("T90 热像仪的探测器分辨率和帧频分别是多少？", 2, ["384", "50"]),
    ("T90 报 F02 故障代码是什么意思，怎么处理？", 5, ["F02", "快门"]),
]


def login() -> str:
    req = urllib.request.Request(  # noqa: S310 —— URL 为硬编码 localhost 常量，不接受外部输入
        f"{BASE}/api/v1/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 —— URL 为硬编码 localhost 常量，不接受外部输入
        return json.loads(r.read().decode())["token"]


def ask(ws, question: str):
    ws.send(json.dumps({"type": "chat_message", "message": question}))
    full, citations = [], []
    t0 = time.time()
    while time.time() - t0 < 300:
        raw = ws.recv(timeout=300)
        msg = json.loads(raw)
        if msg.get("type") == "streaming_chunk":
            full.append(msg.get("text") or msg.get("delta") or "")
            if msg.get("done"):
                citations = msg.get("citations") or []
                break
        elif msg.get("type") in ("error", "transfer_notice"):
            full.append(f"\n[{msg['type']}] {msg}")
            break
    return "".join(full).strip(), citations


def main() -> int:
    from websockets.sync.client import connect

    token = login()
    url = f"ws://127.0.0.1:{PORT}/ws/chat?token={token}"
    all_ok = True
    # 7B 模型在 ReAct 链路下单次要数分钟，期间服务端 WS 循环被同步推理阻塞、
    # 无法回 pong，客户端默认 20s keepalive 会误杀连接。本地验证禁用客户端
    # ping，并把帧间 recv 超时放宽到 300s。
    with connect(url, max_size=None, ping_interval=None, ping_timeout=None) as ws:
        json.loads(ws.recv())  # session_ready
        for idx, (question, expect_page, fact_tokens) in enumerate(CASES, start=1):
            print(f"\n===== 用例{idx}: {question} =====")
            answer, citations = ask(ws, question)
            print(f"[回答] {answer[:220]}")
            print(f"[引用] 共 {len(citations)} 条")
            for c in citations:
                print(
                    f"  - title={c.get('title')!r} source={c.get('source')} "
                    f"page={c.get('page')!r} score={round(c.get('score') or 0, 3)}"
                )
            page_hits = [c for c in citations if c.get("page") == expect_page]
            fact_hits = [t for t in fact_tokens if t in answer]
            ok = bool(page_hits) and bool(fact_hits)
            all_ok &= ok
            print(
                f"[判定] page={expect_page} 命中={bool(page_hits)} "
                f"事实词命中={fact_hits} -> {'PASS' if ok else 'FAIL'}"
            )
    print("\nRESULT:", "ALL PASS" if all_ok else "FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
