#!/usr/bin/env python3
"""金标题库检索层判分 worker（设计在生产 app 容器内运行）。

与生产同构：直接构造 ``HybridRetriever()``（与 src.api.dependencies
的单例构造方式一致），调用 search_with_scores 走向量召回 + RRF +
重排序的真实链路，不另造一套检索逻辑污染基线。

输入：题库 JSON（由宿主编排器把 questions.yaml 转换后 docker cp 入容器）
输出：逐题命中明细 + 汇总指标 JSON

指标定义：
  doc_hit     gold.docs 中任一文档出现在 top_k
  page_hit    对 PDF 题，命中文档的块页码落在 gold.pages 允许列表
  doc_mrr     命中文档的最高倒数排名（1/rank）
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from src.rag.retriever import HybridRetriever


def evaluate(questions: list[dict], top_k: int) -> dict:
    # 与 src.api.dependencies.get_retriever 完全一致的构造口径
    retriever = HybridRetriever()
    rows: list[dict] = []

    for q in questions:
        gold = q.get("gold") or {}
        gold_docs = set(gold.get("docs") or [])
        gold_pages = gold.get("pages") or {}
        skip = bool((q.get("retrieval") or {}).get("skip"))

        row: dict = {
            "id": q["id"],
            "type": q["type"],
            "question": q["question"],
            "skip": skip,
            "gold_docs": sorted(gold_docs),
            "gold_pages": gold_pages,
        }
        if skip:
            row["verdict"] = "skip"
            rows.append(row)
            continue

        t0 = time.perf_counter()
        try:
            hits = retriever.search_with_scores(
                q["question"],
                top_k=top_k,
                tenant_id="default",
            )
        except Exception as e:  # noqa: BLE001 - 单题异常不能中断整批评测
            row["verdict"] = "error"
            row["error"] = f"{type(e).__name__}: {e}"
            rows.append(row)
            continue
        row["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        retrieved = []
        for rank, (doc, score) in enumerate(hits, start=1):
            meta = doc.metadata or {}
            retrieved.append(
                {
                    "rank": rank,
                    "source": meta.get("source"),
                    "page": meta.get("page"),
                    "score": round(float(score), 4),
                }
            )
        row["retrieved"] = retrieved

        doc_hit_rank = next(
            (h["rank"] for h in retrieved if h["source"] in gold_docs),
            None,
        )
        row["doc_hit"] = doc_hit_rank is not None
        row["doc_first_rank"] = doc_hit_rank
        row["doc_mrr"] = round(1.0 / doc_hit_rank, 4) if doc_hit_rank else 0.0

        # 页码核对：仅对声明了 pages 的 PDF 文档判定
        page_details = {}
        for doc_name, allowed_pages in gold_pages.items():
            matched = [
                h["page"]
                for h in retrieved
                if h["source"] == doc_name
                and isinstance(h.get("page"), int)
                and h["page"] in allowed_pages
            ]
            doc_present = any(h["source"] == doc_name for h in retrieved)
            page_details[doc_name] = {
                "doc_present": doc_present,
                "allowed_pages": allowed_pages,
                "matched_pages": sorted(set(matched)),
                "page_hit": bool(matched),
            }
        row["page_details"] = page_details
        row["page_hit"] = (
            all(d["page_hit"] for d in page_details.values()) if page_details else None
        )

        if not gold_docs:
            row["verdict"] = "no_gold_doc"
        elif row["doc_hit"] and row["page_hit"] is not False:
            row["verdict"] = "hit"
        elif row["doc_hit"]:
            row["verdict"] = "doc_only"
        else:
            row["verdict"] = "miss"
        rows.append(row)

    return summarize(rows, top_k)


def summarize(rows: list[dict], top_k: int) -> dict:
    scored = [r for r in rows if not r.get("skip")]
    by_type: dict[str, dict] = {}
    for r in scored:
        bucket = by_type.setdefault(
            r["type"], {"total": 0, "doc_hit": 0, "page_total": 0, "page_hit": 0}
        )
        bucket["total"] += 1
        if r.get("doc_hit"):
            bucket["doc_hit"] += 1
        if r.get("page_hit") is not None:
            bucket["page_total"] += 1
            if r["page_hit"]:
                bucket["page_hit"] += 1

    def pct(n: int, d: int) -> float | None:
        return round(100.0 * n / d, 1) if d else None

    type_metrics = {}
    for t, b in by_type.items():
        type_metrics[t] = {
            "total": b["total"],
            "doc_hit_rate_pct": pct(b["doc_hit"], b["total"]),
            "page_total": b["page_total"],
            "page_hit_rate_pct": pct(b["page_hit"], b["page_total"]),
        }

    total = len(scored)
    doc_hits = sum(1 for r in scored if r.get("doc_hit"))
    page_rows = [r for r in scored if r.get("page_hit") is not None]
    page_hits = sum(1 for r in page_rows if r["page_hit"])
    errors = [r["id"] for r in scored if r.get("verdict") == "error"]
    latencies = [r["elapsed_ms"] for r in scored if "elapsed_ms" in r]

    return {
        "top_k": top_k,
        "scored": total,
        "skipped": sum(1 for r in rows if r.get("skip")),
        "doc_hit_rate_pct": pct(doc_hits, total),
        "page_hit_rate_pct": pct(page_hits, len(page_rows)),
        "doc_mrr": round(sum(r.get("doc_mrr", 0.0) for r in scored) / total, 4)
        if total
        else None,
        "latency_ms": {
            "avg": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "errors": errors,
        "by_type": type_metrics,
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.questions, encoding="utf-8") as f:
        bank = json.load(f)
    top_k = int((bank.get("meta") or {}).get("retrieval_top_k", 10))
    report = evaluate(bank["questions"], top_k)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(
        f"doc_hit={report['doc_hit_rate_pct']}% "
        f"page_hit={report['page_hit_rate_pct']}% "
        f"mrr={report['doc_mrr']} errors={report['errors']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
