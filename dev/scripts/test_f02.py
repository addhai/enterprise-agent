import json, urllib.request, time

BASE = "http://127.0.0.1:8000"

# P0-1 起 /chat 强制登录，先取 JWT
login_body = json.dumps({"username": "admin", "password": "admin123"}).encode()
login_req = urllib.request.Request(
    f"{BASE}/api/v1/auth/login",
    data=login_body,
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(login_req, timeout=30) as r:
    token = json.loads(r.read().decode())["token"]

data = json.dumps({"message": "F02故障代码怎么处理？", "session_id": "debug_f02_fix"}).encode()
req = urllib.request.Request(
    f"{BASE}/api/v1/chat",
    data=data,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    },
)
t0 = time.time()
with urllib.request.urlopen(req, timeout=300) as r:
    resp = json.loads(r.read().decode())
print(f"耗时: {time.time()-t0:.1f}s")
print(f"回复: {resp.get('reply','')}")
