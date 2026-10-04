#!/usr/bin/env python
"""P2-5 性能基准：文件上传 -> 向量化 -> 可检索 端到端耗时

流程：
    1. 创建知识库
    2. 上传 .md 文档（multipart）
    3. 轮询 hit_test 直到能检索到内容（或超时）
    4. 记录每步耗时

无 LLM Key 时向量化会失败，记录到失败行（不等同于脚本崩溃）。

用法：
    python scripts/benchmark/bench_upload_pipeline.py --base-url http://localhost:8000
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# 同目录导入：允许直接 `python scripts/benchmark/bench_upload_pipeline.py` 运行
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from _endpoint import require_http_url  # noqa: E402


def login(base_url: str) -> str:
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


def create_kb(base_url: str, token: str) -> str:
    url = f"{base_url}/api/v1/admin/knowledge"
    payload = json.dumps(
        {
            "name": f"bench_upload_{int(time.time())}",
            "description": "upload pipeline benchmark",
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


def upload_doc(
    base_url: str, token: str, kb_id: str, content: bytes, title: str
) -> dict:
    """上传文档，返回 {status, latency_ms, response}"""
    # 手动构造 multipart/form-data（不依赖 requests 库）
    boundary = "----bench_boundary----"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{title}"\r\n'
            f"Content-Type: text/markdown\r\n\r\n"
        ).encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )

    url = f"{base_url}/api/v1/admin/knowledge/{kb_id}/documents/upload?title={title}"
    req = urllib.request.Request(  # noqa: S310
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            elapsed = (time.perf_counter() - start) * 1000
            return {
                "status": resp.status,
                "latency_ms": elapsed,
                "response": json.loads(resp.read()),
            }
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "status": e.code,
            "latency_ms": elapsed,
            "response": json.loads(e.read() or b"{}"),
        }
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {"status": 0, "latency_ms": elapsed, "response": {"error": str(e)}}


def hit_test(base_url: str, token: str, kb_id: str, query: str) -> dict:
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
            return {
                "status": resp.status,
                "latency_ms": elapsed,
                "response": json.loads(resp.read()),
            }
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "status": e.code,
            "latency_ms": elapsed,
            "response": json.loads(e.read() or b"{}"),
        }
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return {"status": 0, "latency_ms": elapsed, "response": {}}


def main():
    parser = argparse.ArgumentParser(
        description="Upload -> vectorize -> searchable pipeline benchmark"
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--query", default="benchmark test content", help="Query to search after upload"
    )
    args = parser.parse_args()

    # 只允许打 http(s)，防止误传 file: 协议时读到本地文件
    require_http_url(args.base_url, "--base-url")

    print(f"\nBase URL: {args.base_url}")
    print(f"Query: {args.query}\n")

    # 健康检查
    try:
        urllib.request.urlopen(f"{args.base_url}/api/v1/health", timeout=5)  # noqa: S310
    except Exception as e:
        print(f"Health check FAILED: {e}")
        sys.exit(1)

    token = login(args.base_url)
    print("Login: OK\n")

    # Step 1: 创建知识库
    t0 = time.perf_counter()
    kb_id = create_kb(args.base_url, token)
    t_create = (time.perf_counter() - t0) * 1000
    print(f"[1] Create KB: {t_create:.0f}ms (kb_id={kb_id})")

    # Step 2: 上传文档
    doc_content = (
        f"# Benchmark Document\n\n"
        f"This is a test document for the upload pipeline benchmark.\n\n"
        f"Key phrase: {args.query}\n"
    ).encode()

    t1 = time.perf_counter()
    upload_result = upload_doc(args.base_url, token, kb_id, doc_content, "bench_doc.md")
    t_upload = (time.perf_counter() - t1) * 1000
    print(f"[2] Upload:     {t_upload:.0f}ms (status={upload_result['status']})")

    if upload_result["status"] != 200:
        print(f"    Upload failed: {upload_result['response']}")
        print("    (Likely no Embedding API key for vectorization)")
        print("\nPipeline aborted at upload stage.\n")
        return

    doc_id = upload_result["response"].get("document", {}).get("id", "")
    print(f"    doc_id={doc_id}")

    # Step 3: 等待向量化完成，轮询 hit_test
    t2 = time.perf_counter()
    searchable = False
    poll_count = 0
    max_polls = 10
    poll_interval = 2  # seconds

    while poll_count < max_polls:
        poll_count += 1
        ht = hit_test(args.base_url, token, kb_id, args.query)
        if ht["status"] == 200:
            hits = ht["response"].get("hits", [])
            if hits:
                searchable = True
                break
        time.sleep(poll_interval)

    t_searchable = (time.perf_counter() - t2) * 1000
    print(
        f"[3] Searchable: {t_searchable:.0f}ms (polls={poll_count}, found={searchable})"
    )

    # Step 4: hit_test 延迟
    if searchable:
        ht = hit_test(args.base_url, token, kb_id, args.query)
        t_hit = ht["latency_ms"]
        print(
            f"[4] Hit test:  {t_hit:.0f}ms (hits={ht['response'].get('total_hits', 0)})"
        )
    else:
        t_hit = 0
        print("[4] Hit test:  skipped (not searchable)")

    # 汇总
    total = t_create + t_upload + t_searchable + t_hit
    print("\n--- Summary ---")
    print(f"Create KB:     {t_create:>6.0f}ms")
    print(f"Upload:        {t_upload:>6.0f}ms")
    print(f"To searchable: {t_searchable:>6.0f}ms")
    print(f"Hit test:      {t_hit:>6.0f}ms")
    print(f"Total E2E:     {total:>6.0f}ms")

    result = {
        "create_kb_ms": round(t_create, 1),
        "upload_ms": round(t_upload, 1),
        "to_searchable_ms": round(t_searchable, 1),
        "hit_test_ms": round(t_hit, 1),
        "total_e2e_ms": round(total, 1),
        "searchable": searchable,
        "poll_count": poll_count,
    }
    print("\nRaw data (JSON):")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
