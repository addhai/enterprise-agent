#!/usr/bin/env python
"""P2-5 性能基准：REST /chat 并发压测

用法：
    # 需要运行中的服务（默认 localhost:8000）
    python scripts/benchmark/bench_chat_concurrency.py --base-url http://localhost:8000

    # 无 LLM Key 时用 mock 模式（只测框架开销，不触 LLM）
    python scripts/benchmark/bench_chat_concurrency.py --mock

    # 自定义并发档位
    python scripts/benchmark/bench_chat_concurrency.py --levels 10,50,100

输出：
    并发档位 | 请求数 | P50(ms) | P95(ms) | P99(ms) | QPS | 成功率
    ---------+--------+---------+---------+---------+-----+------
    10       | 100    | 45      | 89      | 120     | 180 | 100%
    50       | 100    | 120     | 310     | 450     | 95  | 98%
    100      | 100    | 280     | 620     | 890     | 78  | 95%
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# 同目录导入：允许直接 `python scripts/benchmark/bench_chat_concurrency.py` 运行
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from _endpoint import require_http_url  # noqa: E402


def send_chat(base_url: str, message: str) -> tuple[int, float]:
    """发送一条 chat 请求，返回 (status_code, latency_ms)"""
    url = f"{base_url}/api/v1/chat"
    payload = json.dumps({"message": message}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
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


def run_level(base_url: str, concurrency: int, total: int, mock: bool) -> dict:
    """跑一个并发档位"""
    message = "ping" if mock else "你好，请简单介绍一下产品"
    latencies = []
    errors = 0

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(send_chat, base_url, message) for _ in range(total)]
        for f in as_completed(futures):
            status, lat = f.result()
            if status == 200:
                latencies.append(lat)
            else:
                errors += 1
    # 墙钟耗时 = 整批请求从发出到全部返回的真实时间。
    # QPS 必须用它做分母：并发场景下用单条最大延迟代替会严重高估吞吐。
    wall_ms = (time.perf_counter() - wall_start) * 1000

    latencies.sort()
    n = len(latencies)
    if n == 0:
        return {
            "concurrency": concurrency,
            "total": total,
            "success": 0,
            "errors": errors,
            "p50": 0,
            "p95": 0,
            "p99": 0,
            "qps": 0,
            "success_rate": 0,
        }

    p50 = latencies[int(n * 0.5)]
    p95 = latencies[min(int(n * 0.95), n - 1)]
    p99 = latencies[min(int(n * 0.99), n - 1)]

    qps = n / (wall_ms / 1000) if wall_ms > 0 else 0

    return {
        "concurrency": concurrency,
        "total": total,
        "success": n,
        "errors": errors,
        "p50": round(p50, 1),
        "p95": round(p95, 1),
        "p99": round(p99, 1),
        "qps": round(qps, 1),
        "success_rate": round(n / total * 100, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="REST /chat concurrency benchmark")
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="Base URL of the service"
    )
    parser.add_argument(
        "--levels", default="10,50,100", help="Concurrency levels (comma-separated)"
    )
    parser.add_argument(
        "--total", type=int, default=100, help="Total requests per level"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Mock mode: send minimal payload (no real LLM call expected)",
    )
    args = parser.parse_args()

    # 只允许打 http(s)，防止误传 file: 协议时读到本地文件
    require_http_url(args.base_url, "--base-url")

    levels = [int(x) for x in args.levels.split(",")]
    print(f"\nBase URL: {args.base_url}")
    print(f"Mode: {'mock' if args.mock else 'real'}")
    print(f"Concurrency levels: {levels}")
    print(f"Requests per level: {args.total}\n")

    # 健康检查
    try:
        urllib.request.urlopen(f"{args.base_url}/api/v1/health", timeout=5)  # noqa: S310
        print("Health check: OK\n")
    except Exception as e:
        print(f"Health check FAILED: {e}")
        print("Start the service first: bash deploy/p2/scripts/start.sh")
        sys.exit(1)

    # 表头
    print(
        f"{'并发':>6} | {'请求数':>6} | {'P50(ms)':>8} | {'P95(ms)':>8} | "
        f"{'P99(ms)':>8} | {'QPS':>6} | {'成功率':>6}"
    )
    print("-" * 72)

    results = []
    for level in levels:
        r = run_level(args.base_url, level, args.total, args.mock)
        results.append(r)
        print(
            f"{r['concurrency']:>6} | {r['total']:>6} | {r['p50']:>8} | "
            f"{r['p95']:>8} | {r['p99']:>8} | {r['qps']:>6} | "
            f"{r['success_rate']:>5}%"
        )

    print()
    print("Raw data (JSON):")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
