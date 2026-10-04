"""直接探测 HybridRetriever.search 是否真能返回文档（不依赖运行中的 server）。

用途：定位 RAG 不命中到底是 retriever 过滤把结果吞了，还是 tools.py 旧代码 bug。
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rag.retriever import HybridRetriever

QUERY = "CloudSync API 分页接口 limit 最大值 版本控制 v2 下线 410"


def main():
    print("[init] building HybridRetriever (loads embed model, may take a while)...")
    r = HybridRetriever()
    print(f"[ok] backend={r.backend}, rerank={getattr(r, '_rerank_enabled', '?')}")

    levels = ["public", "internal", "confidential", "restricted"]
    docs = r.search(
        QUERY,
        top_k=3,
        user_id="admin",
        tenant_id="default",
        user_access_levels=levels,
    )
    print(f"\n[RESULT] retriever.search returned {len(docs)} docs")
    for i, d in enumerate(docs, 1):
        src = d.metadata.get("source", "?")
        acl = d.metadata.get("access_level", "?")
        tid = d.metadata.get("tenant_id", "?")
        kb = d.metadata.get("kb_id", "?")
        snippet = d.page_content[:80].replace("\n", " ")
        print(f"  #{i} src={src} tenant={tid} kb={kb} acl={acl}")
        print(f"      {snippet!r}")
    if not docs:
        print("[WARN] empty -> retriever 过滤把结果吞了，与 tools.py 修复无关")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
