# -*- coding: utf-8 -*-
"""诊断 bge-m3 检索：分别看纯向量 / BM25 / 混合召回 top5 的内容与分数"""
import sys
sys.path.insert(0, "/app")
from src.rag.vector_store import VectorStoreManager

vs = VectorStoreManager()
store = vs.store  # langchain Chroma（标准粒度）

for q in ["T100 测温范围", "测温范围 温度区间", "测量温度上下限"]:
    print("\n" + "=" * 70)
    print("Q:", q)
    try:
        results = store.similarity_search_with_relevance_scores(q, k=5)
        for i, (doc, score) in enumerate(results, 1):
            src = doc.metadata.get("source", "?")
            txt = doc.page_content.replace("\n", " ")[:90]
            print(f"  {i}. score={score:.3f} [{src}] {txt}")
    except Exception as e:
        print("  ERR:", e)
