"""抓取多条 RAG 对话，自动挑选命中知识库术语的一条用于 demo GIF（可被 rag_demo_gif.py 直接读取）。

用法：
  1) 先起后端：  uvicorn src.api.server:app --port 8001
  2) python scripts/rag_capture.py         # 默认连 127.0.0.1:8001，可用 DEMO_WS_PORT 覆盖
  产物落在 scripts/.cache/rag_api_best.json（question/reply），不进仓库。
"""
import asyncio
import json
import os

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
os.makedirs(CACHE, exist_ok=True)
PORT = int(os.getenv("DEMO_WS_PORT", "8001"))
WS = f"ws://127.0.0.1:{PORT}/ws/chat"
QUESTION = "CloudSync API 如何做版本控制？请求头里指定版本的字段是什么？分页用哪些参数？请从知识库引用具体字段名。"
# 知识库 api_pagination_versioning.md 特有术语，用于判定 RAG 是否真正命中
KB_HITS = ["vnd.cloudsync", "next_page_token", "offset", "Link 头", "X-API-Version", "page_token"]


async def capture_once(idx: int) -> dict:
    async with websockets.connect(WS) as ws:
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("type") == "session_ready":
                break
        await ws.send(json.dumps({
            "type": "chat_message",
            "session_id": msg.get("session_id"),
            "message": QUESTION,
            "user_id": "demo",
            "tenant_id": "",
        }))
        full = []
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=150)
            except asyncio.TimeoutError:
                break
            m = json.loads(raw)
            if m.get("type") == "streaming_chunk":
                full.append(m.get("text") or m.get("delta") or "")
                if m.get("done"):
                    break
            elif m.get("type") in ("error", "fatal"):
                break
        return {"reply": "".join(full)}


async def main():
    best = None
    runs = int(os.getenv("RAG_RUNS", "5"))
    for i in range(runs):
        try:
            r = await capture_once(i)
        except Exception as e:
            print(f"[run {i}] error: {e}")
            continue
        reply = r["reply"]
        hit = [k for k in KB_HITS if k.lower() in reply.lower()]
        score = len(hit)
        print(f"[run {i}] len={len(reply)} kb_hits={hit}")
        with open(os.path.join(CACHE, f"rag_api_{i}.json"), "w", encoding="utf-8") as f:
            json.dump({"question": QUESTION, "reply": reply}, f, ensure_ascii=False, indent=1)
        # 优先选命中术语最多且最长的
        if best is None or score > best["score"] or (score == best["score"] and len(reply) > best["len"]):
            best = {"idx": i, "score": score, "len": len(reply), "reply": reply}
    print("=" * 40)
    print(f"BEST run {best['idx']} (kb_hits={best['score']}, len={best['len']}):")
    print(best["reply"][:600])
    # 复制最优到固定文件供渲染使用
    with open(os.path.join(CACHE, "rag_api_best.json"), "w", encoding="utf-8") as f:
        json.dump({"question": QUESTION, "reply": best["reply"]}, f, ensure_ascii=False, indent=1)


asyncio.run(main())
