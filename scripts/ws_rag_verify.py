"""临时验证：通过真实 WS 对话验证 RAG 真命中（答案必须来自文档专属事实）。

仅用于本地验证，不纳入 git。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

PORT = int(os.environ.get("RAG_PORT", "8000"))
BASE = f"http://127.0.0.1:{PORT}"

# 文档专属事实（只有 data/docs 里有，LLM 训练集里没有的产品细节）
# api_pagination_versioning.md 内容要点：
#   - limit 最大 100
#   - 游标 cursor 有效期 1 小时
#   - v2 于 2025-12-31 下线，返回 410 Gone
QUESTION = (
    "CloudSync API 的分页接口，单次请求 limit 参数最大能设多少？"
    "v2 版本的分页接口什么时候下线，下线后返回什么 HTTP 状态码？"
)
# 命中判定：回复中应出现这些文档专属 token 中的若干
HIT_TOKENS = ["100", "2025-12-31", "410", "Gone", "游标", "cursor", "1 小时", "一小时"]


def login() -> str:
    req = urllib.request.Request(  # noqa: S310 —— URL 为硬编码 localhost 常量，不接受外部输入
        f"{BASE}/api/v1/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=15)  # noqa: S310 —— URL 为硬编码 localhost 常量，不接受外部输入
    return json.loads(r.read().decode())["token"]


def main():
    from websockets.sync.client import connect

    token = login()
    print(f"[ok] admin token len={len(token)}")

    url = f"ws://127.0.0.1:{PORT}/ws/chat?token={token}"
    with connect(url, max_size=None) as ws:
        ready = json.loads(ws.recv())
        assert ready.get("type") == "session_ready", f"unexpected: {ready}"
        print("[ok] session_ready")

        ws.send(json.dumps({"type": "chat_message", "message": QUESTION}))
        print(f"[>] sent question: {QUESTION}")

        full = []
        done = False
        t0 = time.time()
        while not done and time.time() - t0 < 240:
            try:
                raw = ws.recv(timeout=60)
            except Exception as e:
                print(f"[warn] recv timeout/err: {type(e).__name__} {e}")
                break
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "streaming_chunk":
                chunk = msg.get("text") or msg.get("delta") or ""
                full.append(chunk)
                print(f"  [chunk] {chunk!r}")
                if msg.get("done"):
                    done = True
            elif mtype in ("error", "transfer_notice"):
                print(f"[!] {mtype}: {msg}")
                full.append(f"\n[{mtype}] {msg}")
            else:
                print(f"  [msg:{mtype}] {str(msg)[:160]}")
            # 忽略 typing_indicator / heartbeat 等

        answer = "".join(full)
        print("\n===== AGENT ANSWER =====")
        print(answer)
        print("=======================")

        hits = [t for t in HIT_TOKENS if t.lower() in answer.lower()]
        print(f"\n[verify] hit tokens found: {hits}")
        if hits:
            print(f"[RESULT] RAG HIT ✅ (matched {len(hits)} doc-specific tokens)")
            return 0
        else:
            print("[RESULT] RAG MISS ❌ (answer contains no doc-specific facts)")
            return 1


if __name__ == "__main__":
    sys.exit(main())
