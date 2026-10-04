#!/usr/bin/env python
"""Phase 2 监控流量生成器 —— 让 Grafana 面板真的动起来

为什么要专门造流量：Prometheus 的 rate() 类面板需要至少两个抓取周期内
counter 有增量才会出线。空跑的实例上 QPS / 延迟 / LLM / RAG 面板全是
No data，无法区分「面板配错了」与「本来就没流量」。

三段式设计（对应用户任务单的 4.5 步）：

  第一段 fast：一组轻量 HTTP 请求，含多次 hit_test。
       hit_test 内部会走检索器，因此能产生 rag_search_duration_seconds /
       rag_search_total，且不调用 LLM，秒级完成，适合把时间轴铺开。

  第二段 ws：建立一条 WebSocket 连接并短暂保持，让 ws_active_connections
       gauge 出现非零观测值。

  第三段 chat：调用同步聊天接口，产生 llm_calls_total / llm_tokens_total。
       内网 7B 模型在 CPU 上单轮 4~5 分钟，因此默认只发 1 条并给足超时；
       需要更多数据点时用 --chat-count 调大。

用法：
    python scripts/generate_monitoring_traffic.py
    python scripts/generate_monitoring_traffic.py --chat-count 3 --fast-rounds 12
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8000"
PROM = "http://localhost:9090"


def _req(method: str, url: str, payload=None, token: str = "", timeout: int = 60):
    """最小 HTTP 封装（不依赖 requests，便于在任意环境运行）"""
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # S310: url 全部来自硬编码的 BASE / PROM 常量（均为 localhost），不接受外部输入
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
    try:
        # S310: url 全部来自硬编码的 BASE / PROM 常量（均为 localhost），不接受外部输入
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body)
            except Exception:
                return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def prom_query(expr: str) -> list:
    """查 Prometheus 瞬时值"""
    url = f"{PROM}/api/v1/query?query={urllib.parse.quote(expr)}"
    code, body = _req("GET", url, timeout=15)
    if code != 200 or not isinstance(body, dict):
        return []
    return body.get("data", {}).get("result", [])


def snapshot(tag: str) -> dict:
    """抓一份关键指标的当前值，用于前后对比"""
    out = {}
    for expr in [
        "sum(http_requests_total)",
        "sum(llm_calls_total)",
        "sum(llm_tokens_total)",
        "sum(rag_search_total)",
        "ws_active_connections",
        'up{job="app"}',
    ]:
        res = prom_query(expr)
        if res:
            try:
                out[expr] = round(float(res[0]["value"][1]), 4)
            except Exception:
                out[expr] = res[0]["value"][1]
        else:
            out[expr] = None
    print(
        f"  [{tag}] "
        + ", ".join(f"{k.split('(')[-1].rstrip('){}')}={v}" for k, v in out.items())
    )
    return out


def get_token() -> str:
    code, body = _req(
        "POST",
        f"{BASE}/api/v1/auth/login",
        {"username": "admin", "password": "admin123"},
    )
    if code == 200 and isinstance(body, dict):
        return body.get("token") or body.get("access_token") or ""
    return ""


def get_kb_id(token: str) -> str:
    code, body = _req("GET", f"{BASE}/api/v1/admin/knowledge", token=token)
    if code == 200 and isinstance(body, dict) and body.get("knowledge_bases"):
        return body["knowledge_bases"][0]["id"]
    return ""


def stage_fast(token: str, kb_id: str, rounds: int, sleep_s: float) -> int:
    """轻量 HTTP 流量：把时间轴铺开到多个抓取周期上"""
    print(f"\n[第一段] 轻量 HTTP 流量，{rounds} 轮")
    ok = 0
    for i in range(rounds):
        _req("GET", f"{BASE}/api/v1/health")
        _req("GET", f"{BASE}/api/v1/admin/knowledge", token=token)
        if kb_id:
            # hit_test 会走检索器 → 产生 rag_search_* 指标（不调 LLM，很快）
            code, _ = _req(
                "POST",
                f"{BASE}/api/v1/admin/knowledge/{kb_id}/hit_test",
                {"query": "XG-9000 的腔体预热温度是多少摄氏度", "top_k": 3},
                token=token,
                timeout=120,
            )
            if code == 200:
                ok += 1
        print(f"    第 {i + 1}/{rounds} 轮完成 (hit_test 成功 {ok} 次)")
        time.sleep(sleep_s)
    return ok


def stage_ws(token: str, hold_s: float) -> bool:
    """建一条 WS 连接并保持，让 ws_active_connections 出现非零观测"""
    print(f"\n[第二段] WebSocket 连接保持 {hold_s} 秒")
    try:
        import websocket  # websocket-client
    except ImportError:
        print("    跳过：未安装 websocket-client")
        return False
    try:
        ws = websocket.create_connection(
            f"ws://localhost:8000/ws/chat?token={token}", timeout=10
        )
        try:
            ws.settimeout(5)
            ws.send(json.dumps({"type": "heartbeat"}))
            end = time.time() + hold_s
            while time.time() < end:
                try:
                    ws.recv()
                except Exception:
                    # 压测脚本只关心「连接能建立并保持 hold_s 秒」，
                    # 服务端主动断开或超时都属于预期，不视为错误
                    break
        finally:
            ws.close()
        print("    连接已建立并关闭")
        return True
    except Exception as e:
        print(f"    失败：{type(e).__name__}: {e}")
        return False


def stage_chat(token: str, count: int, timeout: int) -> int:
    """同步聊天流量：产生 llm_calls_total / llm_tokens_total"""
    questions = [
        "XG-9000 的腔体预热温度是多少摄氏度",
        "现场调试交接记录的交接编号是什么",
        "V3 固件升级后腔体预热温度调整为多少摄氏度",
        "安全操作规范里腔体预热期间外壁最高温度是多少",
        "如何校准真空计",
    ]
    print(f"\n[第三段] 同步聊天流量，{count} 条（单条可能耗时数分钟）")
    ok = 0
    for i in range(count):
        q = questions[i % len(questions)]
        t0 = time.time()
        code, body = _req(
            "POST", f"{BASE}/api/v1/chat", {"message": q}, token=token, timeout=timeout
        )
        dt = time.time() - t0
        print(f"    第 {i + 1}/{count} 条 ({dt:.0f}s) HTTP={code} q={q[:22]}")
        if code == 200:
            ok += 1
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast-rounds", type=int, default=8, help="轻量请求轮数")
    ap.add_argument(
        "--fast-sleep",
        type=float,
        default=12.0,
        help="每轮间隔秒数（需覆盖至少两个抓取周期）",
    )
    ap.add_argument("--ws-hold", type=float, default=8.0, help="WS 连接保持秒数")
    ap.add_argument("--chat-count", type=int, default=1, help="同步聊天条数")
    ap.add_argument("--chat-timeout", type=int, default=900, help="单条聊天超时秒数")
    ap.add_argument("--skip-chat", action="store_true", help="跳过聊天（只跑轻量+WS）")
    args = ap.parse_args()

    print("=" * 68)
    print("Phase 2 监控流量生成")
    print("=" * 68)

    token = get_token()
    kb_id = get_kb_id(token)
    print(f"\n登录: {'成功' if token else '失败'}   知识库: {kb_id or '(未找到)'}")

    before = snapshot("发送前")

    hit_ok = stage_fast(token, kb_id, args.fast_rounds, args.fast_sleep)
    stage_ws(token, args.ws_hold)
    chat_ok = 0
    if not args.skip_chat:
        chat_ok = stage_chat(token, args.chat_count, args.chat_timeout)

    # 等 Prometheus 完成至少一轮抓取，避免立刻查询读到旧值
    print("\n等待 20 秒让 Prometheus 完成抓取...")
    time.sleep(20)
    after = snapshot("发送后")

    print("\n" + "=" * 68)
    print("指标变化对比")
    print("=" * 68)
    changed = 0
    for k in before:
        b, a = before[k], after[k]
        mark = "变化" if b != a else "持平"
        if b != a:
            changed += 1
        print(f"  {k:38s} {b} -> {a}   [{mark}]")
    print(
        f"\nhit_test 成功 {hit_ok} 次，聊天成功 {chat_ok} 条，"
        f"指标发生变化 {changed}/{len(before)} 项"
    )
    return 0 if (changed > 0 and hit_ok > 0) else 1


if __name__ == "__main__":
    sys.exit(main())
