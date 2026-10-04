import asyncio
import json
import time
import websockets

async def main():
    url = "ws://localhost:8000/ws/chat"
    question = "帮我查一下有哪些云服务器"
    timeout = 600  # 10分钟，L5修复后应该远小于这个值

    print(f"[Q2] 连接 {url}")
    print(f"[Q2] 问题: {question}")
    print(f"[Q2] 超时: {timeout}s")
    print("-" * 60)

    start = time.time()
    try:
        async with websockets.connect(url, open_timeout=30, close_timeout=10) as ws:
            await ws.send(json.dumps({"type": "chat", "content": question, "session_id": "verify_q2_l5"}))

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    elapsed = time.time() - start
                    print(f"\n[Q2] ❌ 客户端超时 ({elapsed:.1f}s)，L5 修复未生效")
                    return

                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "token":
                    print(msg.get("content", ""), end="", flush=True)
                elif msg_type == "done":
                    elapsed = time.time() - start
                    print(f"\n\n[Q2] ✅ 完成，耗时 {elapsed:.1f}s")
                    # 打印完整消息摘要
                    answer = msg.get("answer", "")
                    citations = msg.get("citations", [])
                    print(f"[Q2] 回答长度: {len(answer)} 字符")
                    print(f"[Q2] citations 数: {len(citations)}")
                    for i, c in enumerate(citations[:5]):
                        print(f"  citation[{i}]: source={c.get('source','?')}, score={c.get('score','?')}")
                    # 关键判定
                    if "思考步数" in answer or "中止" in answer or "转人工" in answer:
                        print("[Q2] ✅ 命中 L5 降级路径（递归上限保护生效）")
                    elif answer.strip():
                        print("[Q2] ⚠️ 有正常回答（模型可能成功调用了工具或直接回答）")
                    return
                elif msg_type == "error":
                    elapsed = time.time() - start
                    print(f"\n[Q2] ❌ 服务端错误 ({elapsed:.1f}s): {msg.get('message','')}")
                    return
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n[Q2] ❌ 异常 ({elapsed:.1f}s): {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
