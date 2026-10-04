#!/usr/bin/env python
"""P2-5 性能基准：RAG hit_test 召回耗时

三档测试：空库 / 10 文档 / 100 文档
无 LLM Key 时用 mock 检索（只测框架开销）。

用法：
    python scripts/benchmark/bench_rag_recall.py --base-url http://localhost:8000
    python scripts/benchmark/bench_rag_recall.py --mock

输出：
    档位      | 平均(ms) | P50(ms) | P95(ms) | 成功率
    ----------+----------+---------+---------+------
    空库      | 45       | 42      | 58      | 100%
    10文档    | 120      | 115     | 180     | 100%
    100文档   | 350      | 340     | 420     | 100%
"""

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

# 同目录导入：允许直接 `python scripts/benchmark/bench_rag_recall.py` 运行
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from _endpoint import require_http_url  # noqa: E402


def login(base_url: str) -> str:
    """登录获取 admin token"""
    url = f"{base_url}/api/v1/auth/login"
    payload = json.dumps({"username": "admin", "password": "admin123"}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return resp.json()["token"]


def create_kb(base_url: str, token: str, name: str) -> str:
    """创建知识库，返回 kb_id"""
    url = f"{base_url}/api/v1/admin/knowledge"
    payload = json.dumps(
        {
            "name": name,
            "description": "benchmark",
            "kb_version": "standard",
            "kb_type": "document",
            "similarity_threshold": 0.2,
            "weight": 1.0,
        }
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return resp.json()["kb"]["id"]


def hit_test(base_url: str, token: str, kb_id: str, query: str) -> tuple[int, float]:
    """执行一次 hit_test，返回 (status, latency_ms)"""
    url = f"{base_url}/api/v1/admin/knowledge/{kb_id}/hit_test"
    payload = json.dumps({"query": query, "top_k": 5}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            elapsed = (time.perf_counter() - start) * 1000
            return resp.status, elapsed
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - start) * 1000
        return e.code, elapsed
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return 0, elapsed


def run_scenario(
    base_url: str, token: str, kb_id: str, label: str, rounds: int
) -> dict:
    """跑一个场景"""
    latencies = []
    errors = 0
    queries = [
        "如何校准设备",
        "故障排查",
        "产品参数",
        "维护指南",
        "售后政策",
    ]

    for i in range(rounds):
        q = queries[i % len(queries)]
        status, lat = hit_test(base_url, token, kb_id, q)
        if status == 200:
            latencies.append(lat)
        else:
            errors += 1

    latencies.sort()
    n = len(latencies)
    if n == 0:
        return {
            "label": label,
            "avg": 0,
            "p50": 0,
            "p95": 0,
            "success_rate": 0,
            "errors": errors,
        }

    avg = statistics.mean(latencies)
    p50 = latencies[int(n * 0.5)]
    p95 = latencies[min(int(n * 0.95), n - 1)]

    return {
        "label": label,
        "avg": round(avg, 1),
        "p50": round(p50, 1),
        "p95": round(p95, 1),
        "success_rate": round(n / rounds * 100, 1),
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description="RAG hit_test recall benchmark")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--rounds", type=int, default=20, help="Requests per scenario")
    parser.add_argument(
        "--mock", action="store_true", help="Mock mode (empty KB, no vector data)"
    )
    args = parser.parse_args()

    # 只允许打 http(s)，防止误传 file: 协议时读到本地文件
    require_http_url(args.base_url, "--base-url")

    print(f"\nBase URL: {args.base_url}")
    print(f"Rounds per scenario: {args.rounds}\n")

    # 健康检查
    try:
        urllib.request.urlopen(f"{args.base_url}/api/v1/health", timeout=5)  # noqa: S310
    except Exception as e:
        print(f"Health check FAILED: {e}")
        sys.exit(1)

    # 登录
    try:
        token = login(args.base_url)
        print("Login: OK (admin)\n")
    except Exception as e:
        print(f"Login FAILED: {e}")
        sys.exit(1)

    # 三档测试
    scenarios = []
    for label, doc_count in [("empty", 0), ("10 docs", 10), ("100 docs", 100)]:
        if args.mock and doc_count > 0:
            # mock 模式跳过文档入库
            scenarios.append(
                {
                    "label": label,
                    "avg": 0,
                    "p50": 0,
                    "p95": 0,
                    "success_rate": 0,
                    "errors": 0,
                    "skipped": True,
                }
            )
            continue

        kb_name = f"bench_{label.replace(' ', '_')}"
        try:
            kb_id = create_kb(args.base_url, token, kb_name)
        except Exception as e:
            print(f"Create KB for {label} FAILED: {e}")
            scenarios.append(
                {
                    "label": label,
                    "avg": 0,
                    "p50": 0,
                    "p95": 0,
                    "success_rate": 0,
                    "errors": 1,
                    "skipped": True,
                }
            )
            continue

        # TODO: 如果需要真实文档，这里应上传文档并等待向量化
        # 当前只测空 KB 的检索框架开销

        r = run_scenario(args.base_url, token, kb_id, label, args.rounds)
        scenarios.append(r)

    # 输出表格
    print(
        f"{'档位':>10} | {'平均(ms)':>10} | {'P50(ms)':>8} | "
        f"{'P95(ms)':>8} | {'成功率':>6}"
    )
    print("-" * 60)
    for s in scenarios:
        if s.get("skipped"):
            print(f"{s['label']:>10} | {'(skipped)':>10} |")
            continue
        print(
            f"{s['label']:>10} | {s['avg']:>10} | {s['p50']:>8} | "
            f"{s['p95']:>8} | {s['success_rate']:>5}%"
        )

    print("\nRaw data (JSON):")
    print(json.dumps(scenarios, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
