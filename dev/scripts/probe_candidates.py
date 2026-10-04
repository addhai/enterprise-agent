"""候选池来源分布取证：看 top_k 截断前，各来源分别占多少名额。

用途：为「来源配额」定值提供数据依据，避免拍脑袋调参。
  docker exec thermo-intranet python scripts/probe_candidates.py
"""

import sys

sys.path.insert(0, "/app")

from src.rag.retriever import HybridRetriever  # noqa: E402

r = HybridRetriever()
QUERIES = ["激光定位灯不亮怎么处理？", "校准对环境有什么要求？", "T100测温范围是多少？"]

for q in QUERIES:
    print("=" * 74)
    print("QUERY:", q)
    vec = r._vector_search(q, 10, None)
    print(f"[向量召回 {len(vec)} 条]")
    for rank, (d, s) in enumerate(vec, start=1):
        src = (d.metadata or {}).get("source", "?")
        preview = d.page_content[:55].replace(chr(10), " ")
        print(f"  v{rank} score={s:.4f} {src} :: {preview}")

    rrf = r._rrf_fusion(vec, [], 10)
    print(f"[RRF 排序 {len(rrf)} 条]")
    from collections import Counter

    cnt = Counter((d.metadata or {}).get("source", "?") for d, _ in rrf)
    for rank, (d, s) in enumerate(rrf, start=1):
        src = (d.metadata or {}).get("source", "?")
        preview = d.page_content[:55].replace(chr(10), " ")
        print(f"  r{rank} score={s:.5f} {src} :: {preview}")
    print("  来源分布:", dict(cnt))
