import asyncio
import json
import time
import websockets

async def main():
    url = "ws://localhost:8000/ws/chat"
    question = "帮我查一下有哪些云服务器"
    session_id = "verify_q2_l5_v2"
    timeout = 900

    print(f"[Q2] connecting {url}")
    print(f"[Q2] type=chat_message, message={question}")
    print(f"[Q2] timeout={timeout}s")
    print("-" * 60)

    start = time.time()
    try:
        async with websockets.connect(url, open_timeout=30, close_timeout=10) as ws:
            # 接收 session_ready
            try:
                ready = await asyncio.wait_for(ws.recv(), timeout=10)
                r = json.loads(ready)
                print(f"[Q2] <-- {r.get('type')}: {str(r.get('message',''))[:40]}")
            except Exception:
                print("[Q2] (no session_ready)")

            # 发送正确格式的聊天消息
            await ws.send(json.dumps({
                "type": "chat_message",
                "message": question,
                "session_id": session_id,
            }))
            print("[Q2] --> sent chat_message")

            full = []
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    print(f"\n[Q2] TIMEOUT after {time.time()-start:.1f}s")
                    return

                msg = json.loads(raw)
                t = msg.get("type", "")

                if t in ("agent_chat_message", "streaming_chunk", "typing_indicator"):
                    chunk = msg.get("content", "") or msg.get("message", "") or msg.get("delta", "")
                    if chunk:
                        print(chunk, end="", flush=True)
                        full.append(chunk)
                elif t in ("agent_send_reply", "done", "complete", "session_update"):
                    answer = msg.get("answer", "") or "".join(full)
                    print(f"\n\n[Q2] done in {time.time()-start:.1f}s")
                    print(f"[Q2] answer ({len(answer)} chars):")
                    print(answer[:800])
                    cites = msg.get("citations", [])
                    print(f"\n[Q2] citations: {len(cites)}")
                    for i, c in enumerate(cites[:5]):
                        print(f"  [{i}] source={c.get('source','?')} score={c.get('score','?')}")
                    if "思考步数" in answer or "中止" in answer or "转人工" in answer:
                        print("\n[Q2] L5 downgrade triggered (recursion limit works)")
                    return
                elif t == "error":
                    print(f"\n[Q2] ERROR: {msg.get('code','')} {msg.get('message','')}")
                    return
                else:
                    print(f"\n[Q2] <-- {t} ({time.time()-start:.1f}s)")
    except Exception as e:
        print(f"\n[Q2] FAILED ({time.time()-start:.1f}s): {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
