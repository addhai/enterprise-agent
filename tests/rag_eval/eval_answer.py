#!/usr/bin/env python
"""P3-1 回答质量评估脚本

对评估集每条 question 评估检索上下文是否包含 expected_keywords。
无 LLM Key 时用 mock 模式（只评估检索到的上下文，不调 LLM 生成）。

用法：
    # 进程内 mock 模式（无需服务、无需 LLM Key）
    python tests/rag_eval/eval_answer.py --in-process

    # 对运行中的服务评估（需 LLM Key）
    python tests/rag_eval/eval_answer.py --base-url http://localhost:8000

输出：
    类型        | 总数 | 关键词命中率 | 引用准确率 | 幻觉率
    -----------+------+-------------+-----------+--------
    fact       | 12   | 85%         | 90%       | 5%
    ...
    ALL        | 33   | 78%         | 82%       | 8%

    未收录准确率: 100% (2/2)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# 确保项目根在 path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def load_dataset(path: str) -> list[dict]:
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def hit_test_inprocess(query: str, top_k: int = 5) -> list[dict]:
    """进程内调用检索器"""
    from fastapi.testclient import TestClient
    from src.api.server import app

    client = TestClient(app)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/admin/knowledge", headers=headers)
    data = resp.json()
    kbs = data.get("knowledge_bases", data.get("items", []))
    if not kbs:
        return []
    kb_id = kbs[0]["id"]

    resp = client.post(
        f"/api/v1/admin/knowledge/{kb_id}/hit_test",
        json={"query": query, "top_k": top_k},
        headers=headers,
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("hits", [])


def chat_http(base_url: str, message: str, token: str | None = None) -> dict:
    """通过 HTTP 调用 /chat

    P0-1 起 /chat 强制 JWT 认证，token 由调用方先登录获取后传入。
    """
    url = f"{base_url}/api/v1/chat"
    payload = json.dumps({"message": message}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url,
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()}
    except Exception as e:
        return {"error": str(e)}


def evaluate_keyword_hit(hits: list[dict], expected_keywords: list[str]) -> dict:
    """评估检索到的上下文是否包含 expected_keywords

    返回 {hit_count, total, hit_rate, missing_keywords}
    """
    # 拼接所有命中片段的文本
    context = " ".join(h.get("content", "") for h in hits)

    hit_count = 0
    missing = []
    for kw in expected_keywords:
        if kw.lower() in context.lower():
            hit_count += 1
        else:
            missing.append(kw)

    total = len(expected_keywords)
    hit_rate = hit_count / total if total > 0 else 0

    return {
        "hit_count": hit_count,
        "total": total,
        "hit_rate": round(hit_rate * 100, 1),
        "missing_keywords": missing,
        "context_length": len(context),
    }


def evaluate_citation_accuracy(hits: list[dict], expected_doc: str) -> dict:
    """评估引用准确率：检索到的文档是否包含期望文档"""
    if not expected_doc:
        return {"accurate": True, "note": "N/A (unknown type)"}

    for h in hits:
        source = h.get("source", "")
        if expected_doc in source or source in expected_doc:
            return {"accurate": True, "matched_source": source}

    return {"accurate": False, "matched_source": None}


def evaluate_unknown_accuracy(hits: list[dict], question: str) -> dict:
    """评估未收录准确率

    未收录类（expected_doc=None）的正确行为是返回零命中
    或返回的上下文不包含具体答案。
    """
    has_hits = len(hits) > 0
    # 如果有命中但命中内容是通用的（如FAQ列表），也算部分正确
    return {
        "has_hits": has_hits,
        "correct": not has_hits,  # 零命中是正确行为
        "hit_count": len(hits),
    }


def main():
    parser = argparse.ArgumentParser(description="RAG answer quality evaluation")
    parser.add_argument("--dataset", default=None, help="Path to eval_dataset.jsonl")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--in-process", action="store_true", help="In-process mock mode"
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    if args.dataset is None:
        args.dataset = os.path.join(os.path.dirname(__file__), "eval_dataset.jsonl")

    dataset = load_dataset(args.dataset)
    print(f"\nDataset: {args.dataset}")
    print(f"Total: {len(dataset)} questions")
    print(f"Mode: {'in-process (mock)' if args.in_process else 'http'}")
    print(f"Top-K: {args.top_k}\n")

    # 选择检索函数
    if args.in_process:

        def retrieve_fn(query):
            return hit_test_inprocess(query, args.top_k)
    else:
        try:
            urllib.request.urlopen(f"{args.base_url}/api/v1/health", timeout=5)
        except Exception as e:
            print(f"Health check FAILED: {e}")
            print("Use --in-process for mock evaluation")
            sys.exit(1)

        def retrieve_fn(query):
            # HTTP 模式需要登录+获取KB，简化：直接用 hit_test
            token = None
            try:
                login_url = f"{args.base_url}/api/v1/auth/login"
                payload = json.dumps(
                    {"username": "admin", "password": "admin123"}
                ).encode("utf-8")
                req = urllib.request.Request(
                    login_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    token = json.loads(resp.read())["token"]

                # 获取 KB
                kb_url = f"{args.base_url}/api/v1/admin/knowledge"
                req = urllib.request.Request(
                    kb_url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    kbs = json.loads(resp.read()).get("knowledge_bases", [])
                    if not kbs:
                        return []
                    kb_id = kbs[0]["id"]

                # hit_test
                ht_url = f"{args.base_url}/api/v1/admin/knowledge/{kb_id}/hit_test"
                payload = json.dumps({"query": query, "top_k": args.top_k}).encode(
                    "utf-8"
                )
                req = urllib.request.Request(
                    ht_url,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read()).get("hits", [])
            except Exception:
                return []

    # 评估
    print("Running evaluation...\n")
    results = []
    for item in dataset:
        qid = item["id"]
        question = item["question"]
        expected_doc = item.get("expected_doc")
        expected_keywords = item.get("expected_keywords", [])
        qtype = item["type"]

        # 检索
        hits = retrieve_fn(question)

        # 评估关键词命中
        kw_result = evaluate_keyword_hit(hits, expected_keywords)

        # 评估引用准确率
        cite_result = evaluate_citation_accuracy(hits, expected_doc)

        # 未收录类特殊评估
        if expected_doc is None:
            unknown_result = evaluate_unknown_accuracy(hits, question)
        else:
            unknown_result = None

        results.append(
            {
                "id": qid,
                "type": qtype,
                "question": question,
                "expected_doc": expected_doc,
                "keyword_hit_rate": kw_result["hit_rate"],
                "keyword_missing": kw_result["missing_keywords"],
                "citation_accurate": cite_result["accurate"],
                "context_length": kw_result["context_length"],
                "hit_count": len(hits),
                "unknown_result": unknown_result,
            }
        )

    # 统计
    known = [r for r in results if r["expected_doc"] is not None]
    unknown = [r for r in results if r["expected_doc"] is None]

    def avg(items, key):
        vals = [r[key] for r in items if key in r]
        return round(sum(vals) / len(vals), 1) if vals else 0

    # 按类型分组
    print(
        f"{'类型':>10} | {'总数':>4} | "
        f"{'关键词命中率':>12} | {'引用准确率':>10} | {'平均命中数':>10}"
    )
    print("-" * 68)
    for qtype in ["fact", "fault", "operation", "parameter"]:
        type_items = [r for r in known if r["type"] == qtype]
        if type_items:
            kw_avg = avg(type_items, "keyword_hit_rate")
            cite_rate = round(
                sum(1 for r in type_items if r["citation_accurate"])
                / len(type_items)
                * 100,
                1,
            )
            hit_avg = avg(type_items, "hit_count")
            print(
                f"{qtype:>10} | {len(type_items):>4} | "
                f"{kw_avg:>10}% | {cite_rate:>9}% | {hit_avg:>10}"
            )

    # 总体
    kw_avg = avg(known, "keyword_hit_rate")
    cite_rate = round(
        sum(1 for r in known if r["citation_accurate"]) / len(known) * 100, 1
    )
    hit_avg = avg(known, "hit_count")
    print("-" * 68)
    print(
        f"{'ALL':>10} | {len(known):>4} | "
        f"{kw_avg:>10}% | {cite_rate:>9}% | {hit_avg:>10}"
    )

    # 未收录类
    if unknown:
        correct = sum(
            1 for r in unknown if r["unknown_result"] and r["unknown_result"]["correct"]
        )
        rate = round(correct / len(unknown) * 100, 1)
        print(
            f"\n{'unknown':>10} | {len(unknown):>4} | "
            f"未收录准确率: {rate}% ({correct}/{len(unknown)})"
        )

    # 幻觉率估算（mock 模式）
    # 幻觉率 = 关键词未命中的比例（上下文不含答案，LLM 可能编造）
    hallucination_est = round(100 - kw_avg, 1)
    print(f"\n幻觉率估算（mock）: {hallucination_est}% (= 100% - 关键词命中率)")

    # 逐条详情
    print("\n--- Per-question details ---")
    for r in results:
        status = (
            f"kw={r['keyword_hit_rate']}% "
            f"cite={'Y' if r['citation_accurate'] else 'N'} "
            f"hits={r['hit_count']}"
        )
        if r["keyword_missing"]:
            status += f" missing={r['keyword_missing']}"
        print(f"  {r['id']:>4} [{r['type']:>9}] {status}")

    # JSON 输出
    print("\n--- Raw JSON ---")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
