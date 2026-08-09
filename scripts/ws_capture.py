"""连本地 WS /ws/chat，发两段 CloudSync 场景消息，存盘用于 GIF 素材（可被 make_demo_gif.py 直接读取）。

用法：
  1) 先起后端：  uvicorn src.api.server:app --port 8001
  2) python scripts/ws_capture.py            # 默认连 127.0.0.1:8001，可用 DEMO_WS_PORT 覆盖
  产物落在 scripts/.cache/ws_reply.json（q1/a1/q2/a2），不进仓库。
"""
import asyncio
import json
import os

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
os.makedirs(CACHE, exist_ok=True)
PORT = int(os.getenv("DEMO_WS_PORT", "8001"))
URI = f"ws://127.0.0.1:{PORT}/ws/chat"

MSG1 = "我的 Google Drive 同步一直失败，提示 API 速率限制(rate limit)错误，应该怎么解决？"
MSG2 = "帮我创建一个工单，标题：Dropbox 同步中断，问题描述：用户反馈 Dropbox 连接频繁断开，优先级：高"

async def capture_one(ws, message):
    await ws.send(json.dumps({"type": "chat_message", "message": message, "session_id": ""}))
    chunks = []
    full = ""
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
        except asyncio.TimeoutError:
            break
        d = json.loads(raw)
        t = d.get("type")
        if t == "streaming_chunk":
            c = d.get("text") or d.get("delta") or d.get("content") or ""
            if isinstance(c, str):
                full += c
            if d.get("done"):
                break
        elif t == "typing_indicator":
            pass
        else:
            chunks.append(d)
    return full

async def main():
    r1 = r2 = ""
    try:
        async with websockets.connect(URI, max_size=2**23) as ws:
            # 丢弃首条 session_ready
            await asyncio.wait_for(ws.recv(), timeout=10)
            print(">> Q1:", MSG1)
            r1 = await capture_one(ws, MSG1)
            print("A1:", r1[:200], "\n")
            print(">> Q2:", MSG2)
            r2 = await capture_one(ws, MSG2)
            print("A2:", r2[:200], "\n")
    except Exception as e:
        print("WS ERROR:", type(e).__name__, str(e)[:200])
    json.dump({"q1": MSG1, "a1": r1, "q2": MSG2, "a2": r2},
              open(os.path.join(CACHE, "ws_reply.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n=== A1 FULL ===\n" + r1)
    print("\n=== A2 FULL ===\n" + r2)

if __name__ == "__main__":
    asyncio.run(main())
