import json, urllib.request, time
data = json.dumps({"message":"F02故障代码怎么处理？","session_id":"debug_f02_fix"}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/api/v1/chat", data=data, headers={"Content-Type":"application/json"})
t0 = time.time()
with urllib.request.urlopen(req, timeout=300) as r:
    resp = json.loads(r.read().decode())
print(f"耗时: {time.time()-t0:.1f}s")
print(f"回复: {resp.get('reply','')}")
