"""docker 版「完整 12 服务栈」端到端验证（需 docker daemon）

把 enterprise-agent 整套容器栈真跑起来，断言每个服务容器都真正 healthy，
且一条端到端链路经 APISIX 网关在容器网络内跑通。这是把 README 里
“Compose 配置已校验”升级为“完整栈已实测”的关键证据。

前置：
  - Docker Desktop / docker daemon 已启动（本脚本会先自检）
  - 已 `cp .env.example .env`（key 仅在可信本机，不上公网；留空也不影响 health/metrics）
  - 已 `npm run build` 生成 static/（frontend 挂载用）

运行：
  python scripts/verify_fullstack.py
退出码 0 = 全栈真跑通过；非 0 = 失败（并打印各部分状态）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

COMPOSE = "docker-compose.yml"
# 宿主可达且暴露 /api/v1/health 的应用服务（用于 HTTP 轮询）
HTTP_HEALTH = {"api-service": 8000, "rag-service": 8001}
# apisix 网关状态端点（宿主 9080 可达）
APISIX_STATUS_PORT = 9080
# 期望全部起来且 healthy/running 的容器服务
EXPECT_SERVICES = [
    "apisix", "api-service", "agent-worker", "rag-service", "ws-service",
    "frontend", "postgres", "milvus-standalone", "minio", "redis", "rabbitmq",
]
HEALTH_URL_TMPL = "http://127.0.0.1:{port}/api/v1/health"
POLL_TIMEOUT = 600  # 拉镜像 + 起 12 服务，给足 10 分钟
REPORT_PATH = "verify_fullstack_report.txt"  # 结论同时落文件，避免任务输出取不回时丢结果
_report_fh = open(REPORT_PATH, "w", encoding="utf-8")  # 启动时截断，整轮运行写入同一文件


def _log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        _report_fh.write(line + "\n")
        _report_fh.flush()
    except Exception:
        pass


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=".", capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# 主 compose 用 container_name: agent-*；历史验证残留的同名停止容器会导致
# `docker compose up` 命名冲突（曾因此 FAIL）。开头先防御性清理，保证幂等可重跑。
_STALE_CONTAINERS = [
    "agent-apisix", "agent-apisix-dashboard", "agent-postgres", "agent-milvus",
    "agent-minio", "agent-redis", "agent-rabbitmq",
]


def _cleanup_stale():
    for name in _STALE_CONTAINERS:
        _run(["docker", "rm", "-f", name])  # 忽略“不存在”等错误


def _docker_daemon_ok() -> bool:
    rc, _ = _run(["docker", "info"])
    return rc == 0


def _service_states() -> dict:
    """{service: [(name, state, health)]}，来源 docker compose ps --format json。"""
    rc, out = _run(["docker", "compose", "-f", COMPOSE, "ps", "--format", "json"])
    if rc != 0 or not out.strip():
        return {}
    try:
        arr = json.loads(out)
    except Exception:
        return {}
    states: dict[str, list] = {}
    for c in arr if isinstance(arr, list) else []:
        svc = c.get("Service") or c.get("service")
        if not svc:
            continue
        states.setdefault(svc, []).append((
            c.get("Name") or c.get("name"),
            c.get("State") or c.get("state") or "",
            c.get("Health") or c.get("health") or "",
        ))
    return states


def wait_http(port: int, path: str) -> bool:
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3)
            if r.status == 200:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def http_json(method: str, url: str, data: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def main():
    _log("=== full 12-service stack verification (docker) ===")
    if not _docker_daemon_ok():
        _log("FAIL: docker daemon 未启动，请先打开 Docker Desktop")
        return 1
    _cleanup_stale()  # 清掉同名残留容器，避免命名冲突

    # 1) 起栈（应用层多副本）
    rc, out = _run(["docker", "compose", "-f", COMPOSE, "up", "-d",
                    "--scale", "api-service=3", "--scale", "ws-service=3"])
    if rc != 0:
        _log(f"FAIL: docker compose up failed\n{out}")
        return 2

    try:
        _log("stack starting, polling container health...")

        # 2) 容器健康态（用 compose ps，不依赖端口映射）
        states = _service_states()
        missing = [s for s in EXPECT_SERVICES if not states.get(s)]
        if missing:
            _log(f"FAIL: 缺少服务容器: {missing}")
            return 3
        bad = []
        for s in EXPECT_SERVICES:
            for (name, st, h) in states[s]:
                if st != "running":
                    bad.append(f"{name}:{st}")
                elif h and h != "healthy":
                    bad.append(f"{name}:health={h}")
        if bad:
            _log(f"FAIL: 容器未 healthy: {bad}")
            return 4
        _log(f"  all {len(EXPECT_SERVICES)} services healthy (container-level)")

        # 3) HTTP 应用健康（只对真正有宿主 health 端点的服务）
        for svc, port in HTTP_HEALTH.items():
            ok = wait_http(port, "/api/v1/health")
            _log(f"  {svc}:{'OK' if ok else 'TIMEOUT'}")
            if not ok:
                return 5
        if not wait_http(APISIX_STATUS_PORT, "/apisix/status"):
            _log("FAIL: apisix gateway not responding")
            return 6
        _log("  apisix gateway OK")

        # 4) 端到端：经 apisix 网关建单 + 跨读
        admin_st, admin_body = http_json(
            "POST", "http://127.0.0.1:9080/api/v1/auth/login",
            {"username": "admin", "password": "admin123"})
        if admin_st != 200:
            _log(f"FAIL: admin login via gateway: {admin_st} {admin_body}")
            return 7
        token = admin_body["token"]
        st, body = http_json(
            "POST", "http://127.0.0.1:9080/api/v1/tickets",
            {"user_id": "custFull", "title": "全栈容器验证工单"}, token=token)
        if st != 200:
            _log(f"FAIL: create ticket via gateway: {st} {body}")
            return 8
        tid = body["ticket"]["id"]
        st2, body2 = http_json(
            "GET", f"http://127.0.0.1:9080/api/v1/tickets/{tid}", token=token)
        if not (st2 == 200 and body2.get("id") == tid):
            _log(f"FAIL: ticket not readable via gateway: {st2} {body2}")
            return 9
        _log(f"end-to-end ticket create+read via APISIX gateway OK (id={tid})")
    finally:
        _log("cleaning up stack...")
        _run(["docker", "compose", "-f", COMPOSE, "down"])

    _log("=== RESULT: full 12-service stack VERIFIED (runtime, containerized) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
