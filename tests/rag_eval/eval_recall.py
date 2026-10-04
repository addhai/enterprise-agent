#!/usr/bin/env python
"""P3-1 召回率评估脚本（直接模式）

直接加载 7 篇知识库文档，用 BM25 + 章节切块做检索，
不依赖 Chroma 向量库或运行中的服务。

用法：
    python tests/rag_eval/eval_recall.py --direct
    python tests/rag_eval/eval_recall.py --direct --top-k 5

输出：
    类型        | 总数 | Hit@1 | Hit@3 | Hit@5 | MRR
    -----------+------+-------+-------+-------+------
    fact       | 12   | 75%   | 92%   | 100%  | 0.85
    ...
"""

import argparse
import json
import os
import sys
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


def load_and_chunk_docs(docs_dir: str) -> list[dict]:
    """加载知识库文档并按章节切块

    返回 [{source, content, chapter}] 列表
    """
    from src.rag.chunker import HybridChunker
    from src.rag.loader import DocumentLoader

    loader = DocumentLoader()
    chunker = HybridChunker()

    chunks = []
    for md_file in sorted(Path(docs_dir).glob("*.md")):
        docs = loader.load_file(str(md_file))
        std_chunks, _ = chunker.split_both(docs, source_file=md_file.name)
        for c in std_chunks:
            c.metadata["source"] = md_file.name
            chunks.append(
                {
                    "source": md_file.name,
                    "content": c.page_content,
                    "metadata": c.metadata,
                }
            )

    return chunks


def bm25_search(chunks: list[dict], query: str, top_k: int = 5) -> list[dict]:
    """BM25 关键词搜索

    返回 [{source, content, score}] 列表，按相关性降序
    """
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        # 降级：简单的关键词匹配
        return _keyword_search(chunks, query, top_k)

    # 中文分词：按字符切分（无需 jieba）
    corpus = [list(c["content"]) for c in chunks]
    query_tokens = list(query)

    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(query_tokens)

    # 按分数排序
    ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
    results = []
    for score, chunk in ranked[:top_k]:
        results.append(
            {
                "source": chunk["source"],
                "content": chunk["content"][:200],
                "score": float(score),
            }
        )
    return results


def _keyword_search(chunks: list[dict], query: str, top_k: int = 5) -> list[dict]:
    """降级关键词搜索（无 rank_bm25 时）"""
    query_lower = query.lower()
    scored = []
    for chunk in chunks:
        content_lower = chunk["content"].lower()
        # 统计查询词在文档中的出现次数
        score = 0
        for char in query_lower:
            if char.isalnum():
                score += content_lower.count(char)
        scored.append((score, chunk))

    ranked = sorted(scored, key=lambda x: x[0], reverse=True)
    results = []
    for score, chunk in ranked[:top_k]:
        results.append(
            {
                "source": chunk["source"],
                "content": chunk["content"][:200],
                "score": float(score),
            }
        )
    return results


def evaluate_recall(
    dataset: list[dict],
    chunks: list[dict],
    top_k: int = 5,
    hit_fn=None,
) -> dict:
    """评估召回率

    hit_fn(query, top_k) -> List[dict]，每个 dict 含 source 字段。
    不传 hit_fn 时默认用 bm25_search。
    """
    if hit_fn is None:

        def hit_fn(q, k, _chunks=chunks):  # noqa: ANN001,E306 —— 闭包捕获本次加载的切块
            return bm25_search(_chunks, q, k)

    results = []
    for item in dataset:
        qid = item["id"]
        question = item["question"]
        expected_doc = item.get("expected_doc")
        qtype = item["type"]

        hits = hit_fn(question, top_k)
        sources = [h["source"] for h in hits]

        # 计算排名
        rank = 0
        if expected_doc:
            for i, src in enumerate(sources):
                if expected_doc in src or src in expected_doc:
                    rank = i + 1
                    break

        results.append(
            {
                "id": qid,
                "type": qtype,
                "question": question,
                "expected_doc": expected_doc,
                "sources": sources,
                "rank": rank,
                "has_hits": len(sources) > 0,
            }
        )

    known = [r for r in results if r["expected_doc"] is not None]
    unknown = [r for r in results if r["expected_doc"] is None]

    def calc_metrics(items):
        total = len(items)
        if total == 0:
            return {"hit1": 0, "hit3": 0, "hit5": 0, "mrr": 0, "total": 0}
        hit1 = sum(1 for r in items if r["rank"] == 1) / total
        hit3 = sum(1 for r in items if 1 <= r["rank"] <= 3) / total
        hit5 = sum(1 for r in items if 1 <= r["rank"] <= 5) / total
        mrr = sum(1 / r["rank"] for r in items if r["rank"] > 0) / total
        return {
            "hit1": round(hit1 * 100, 1),
            "hit3": round(hit3 * 100, 1),
            "hit5": round(hit5 * 100, 1),
            "mrr": round(mrr, 3),
            "total": total,
        }

    overall = calc_metrics(known)
    by_type = {}
    for qtype in ["fact", "fault", "operation", "parameter"]:
        type_items = [r for r in known if r["type"] == qtype]
        by_type[qtype] = calc_metrics(type_items)

    unknown_stats = {
        "total": len(unknown),
        "has_hits": sum(1 for r in unknown if r["has_hits"]),
        "no_hits": sum(1 for r in unknown if not r["has_hits"]),
    }

    return {
        "overall": overall,
        "by_type": by_type,
        "unknown": unknown_stats,
        "details": results,
        "total_chunks": len(chunks),
    }


def main():
    parser = argparse.ArgumentParser(description="RAG recall evaluation")
    parser.add_argument("--dataset", default=None, help="Path to eval_dataset.jsonl")
    parser.add_argument("--docs-dir", default=None, help="Path to knowledge base docs")
    parser.add_argument(
        "--direct", action="store_true", help="Direct BM25 mode (no service needed)"
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--in-process", action="store_true", help="In-process mode (TestClient)"
    )
    parser.add_argument(
        "--mode",
        default="direct",
        choices=["direct", "hybrid", "rewrite", "weighted", "combo"],
        help="direct=BM25 only, hybrid=vector+BM25 RRF "
        "(needs running service), rewrite=query rewriting, "
        "weighted=doc weight boost, combo=rewrite+weighted",
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    if args.dataset is None:
        args.dataset = os.path.join(os.path.dirname(__file__), "eval_dataset.jsonl")
    if args.docs_dir is None:
        args.docs_dir = str(_PROJECT_ROOT / "data" / "docs")

    dataset = load_dataset(args.dataset)
    print(f"\nDataset: {args.dataset}")
    print(f"Total: {len(dataset)} questions")
    print(f"Top-K: {args.top_k}")

    mode = args.mode
    if args.direct:
        mode = "direct"
    if args.in_process:
        mode = "direct"

    if mode == "hybrid":
        # 混合检索模式：需要运行中的服务 + 向量库
        print("Mode: hybrid (vector bge-m3 + BM25 RRF)")
        print(f"Base URL: {args.base_url}\n")
        try:
            import urllib.request as urlreq

            urlreq.urlopen(f"{args.base_url}/api/v1/health", timeout=5)
        except Exception as e:
            print(f"Health check FAILED: {e}")
            print("Hybrid mode needs a running service with vector store.")
            print("Start service: bash deploy/p2/scripts/start.sh")
            print("Or use --mode direct/rewrite/weighted/combo for BM25-based modes.")
            sys.exit(1)

        token = None
        try:
            login_url = f"{args.base_url}/api/v1/auth/login"
            payload = json.dumps({"username": "admin", "password": "admin123"}).encode(
                "utf-8"
            )
            req = urllib.request.Request(
                login_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                token = json.loads(resp.read())["token"]
            kb_url = f"{args.base_url}/api/v1/admin/knowledge"
            req = urllib.request.Request(
                kb_url,
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                kbs = json.loads(resp.read()).get("knowledge_bases", [])
                if not kbs:
                    print("No knowledge base found")
                    sys.exit(1)
                kb_id = kbs[0]["id"]
        except Exception as e:
            print(f"Login/KB setup FAILED: {e}")
            sys.exit(1)

        def hit_fn(query, top_k):
            ht_url = f"{args.base_url}/api/v1/admin/knowledge/{kb_id}/hit_test"
            payload = json.dumps({"query": query, "top_k": top_k}).encode("utf-8")
            req = urllib.request.Request(
                ht_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read()).get("hits", [])
            except Exception:
                return []

    elif mode in ("direct", "rewrite", "weighted", "combo"):
        # BM25-based 模式
        mode_label = {
            "direct": "direct (BM25, no optimization)",
            "rewrite": "rewrite (query rewriting + BM25)",
            "weighted": "weighted (doc weight boost + BM25)",
            "combo": "combo (rewrite + weight + BM25)",
        }[mode]
        print(f"Mode: {mode_label}")
        print(f"Docs dir: {args.docs_dir}\n")

        print("Loading and chunking documents...")
        chunks = load_and_chunk_docs(args.docs_dir)
        n_sources = len({c["source"] for c in chunks})
        print(f"Loaded {len(chunks)} chunks from {n_sources} documents\n")

        if mode in ("rewrite", "combo"):
            from tests.rag_eval.query_rewriter import QueryRewriter

            rewriter = QueryRewriter()
            # 改写评估集中的 question
            dataset = [
                {**item, "question": rewriter.rewrite(item["question"])}
                for item in dataset
            ]
            print("Query rewriting applied.\n")

        if mode in ("weighted", "combo"):
            # 文档权重 boost
            WEIGHTS = {
                "fault_troubleshooting_manual.md": 1.5,
                "calibration_guide.md": 1.3,
                "faq_full.md": 0.8,
                "application_guide.md": 0.9,
                "product_spec_manual.md": 1.2,
                "after_sales_policy.md": 1.1,
                "maintenance_guide.md": 1.0,
            }
            from rank_bm25 import BM25Okapi

            corpus = [list(c["content"]) for c in chunks]
            bm25_engine = BM25Okapi(corpus)

            def hit_fn(query, top_k):
                tokens = list(query)
                scores = bm25_engine.get_scores(tokens)
                for i, chunk in enumerate(chunks):
                    w = WEIGHTS.get(chunk["source"], 1.0)
                    scores[i] *= w
                ranked = sorted(
                    zip(scores, chunks),
                    key=lambda x: x[0],
                    reverse=True,
                )
                results = []
                for score, chunk in ranked[:top_k]:
                    results.append(
                        {
                            "source": chunk["source"],
                            "content": chunk["content"][:200],
                            "score": float(score),
                        }
                    )
                return results
        else:

            def hit_fn(query, top_k):
                return bm25_search(chunks, query, top_k)
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)
        print("Use --direct for direct BM25 evaluation\n")
        sys.exit(0)

    # 评估
    print("Running evaluation...\n")
    result = evaluate_recall(dataset, chunks, args.top_k, hit_fn=hit_fn)

    # 输出表格
    print(
        f"{'类型':>10} | {'总数':>4} | "
        f"{'Hit@1':>6} | {'Hit@3':>6} | {'Hit@5':>6} | {'MRR':>6}"
    )
    print("-" * 56)
    for qtype, m in result["by_type"].items():
        if m["total"] > 0:
            print(
                f"{qtype:>10} | {m['total']:>4} | "
                f"{m['hit1']:>5}% | {m['hit3']:>5}% | "
                f"{m['hit5']:>5}% | {m['mrr']:>6}"
            )
    ov = result["overall"]
    print("-" * 56)
    print(
        f"{'ALL':>10} | {ov['total']:>4} | "
        f"{ov['hit1']:>5}% | {ov['hit3']:>5}% | "
        f"{ov['hit5']:>5}% | {ov['mrr']:>6}"
    )

    unk = result["unknown"]
    if unk["total"] > 0:
        print(
            f"\n{'unknown':>10} | {unk['total']:>4} | "
            f"(有命中: {unk['has_hits']}, 无命中: {unk['no_hits']})"
        )

    # 逐条详情
    print("\n--- Per-question details ---")
    for r in result["details"]:
        if r["expected_doc"] is None:
            print(f"  {r['id']:>4} [{r['type']:>9}] hits={len(r['sources'])} (unknown)")
        else:
            rank_str = str(r["rank"]) if r["rank"] > 0 else "MISS"
            srcs = [s[:20] for s in r["sources"][:3]]
            print(
                f"  {r['id']:>4} [{r['type']:>9}] "
                f"rank={rank_str:>4} "
                f"expected={r['expected_doc'][:25]:>25} "
                f"sources={srcs}"
            )

    print(f"\nTotal chunks: {result['total_chunks']}")
    print(f"Documents: {len({c['source'] for c in chunks})}")


if __name__ == "__main__":
    main()
