import json, time, urllib.request

API_BASE = "http://localhost:8000"
question = "帮我查一下有哪些云服务器"
session_id = "verify_q2_l5_http"
timeout = 900

body = json.dumps({"question": question, "session_id": session_id}).encode("utf-8")
req = urllib.request.Request(
    f"{API_BASE}/api/chat",
    data=body,
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)

print(f"[Q2] POST {API_BASE}/api/chat")
print(f"[Q2] question: {question}")
print(f"[Q2] timeout: {timeout}s")
print("-" * 60)

t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    elapsed = time.time() - t0
    print(f"\n[Q2] done in {elapsed:.1f}s")
    answer = payload.get("answer", "")
    print(f"[Q2] answer ({len(answer)} chars):")
    print(answer[:800])
    citations = payload.get("citations", [])
    print(f"\n[Q2] citations: {len(citations)}")
    for i, c in enumerate(citations[:5]):
        print(f"  [{i}] source={c.get('source','?')} score={c.get('score','?')}")
    if "思考步数" in answer or "中止" in answer or "转人工" in answer:
        print("\n[Q2] L5 downgrade triggered (recursion limit works)")
    elif answer.strip():
        print("\n[Q2] got normal answer")
except Exception as e:
    elapsed = time.time() - t0
    print(f"\n[Q2] FAILED ({elapsed:.1f}s): {type(e).__name__}: {e}")
