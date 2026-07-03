#!/usr/bin/env python
"""将 data/docs/ 下的所有文档加载、切块、入库到 Chroma

v0.3 更新（2026-07-01）：
    - 支持 PDF / HTML 加载
    - 元数据保留（文件名、页码、类别、时间戳）
    - 文本规范化 + 质量过滤 + 去重
    - 混合切块：标准粒度 + 句子窗口粒度
"""

import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag.loader import DocumentLoader
from src.rag.chunker import HybridChunker
from src.rag.vector_store import VectorStoreManager
from src.config import settings


def main():
    print("=" * 50)
    print("CloudSync Knowledge Base Ingestion (v0.3)")
    print("=" * 50)

    docs_dir = Path(__file__).parent.parent / "data" / "docs"

    # ---- 1. 加载文档（含清洗） ----
    print(f"\n[1/5] Loading documents from {docs_dir}...")
    loader = DocumentLoader(enable_dedup=True)
    documents = loader.load_directory(str(docs_dir))
    print(f"  Loaded {len(documents)} document(s)")

    # 打印元数据统计
    if documents:
        sources = set(d.metadata.get("source", "?") for d in documents)
        categories = set(d.metadata.get("category", "?") for d in documents)
        print(f"  Sources: {sources}")
        print(f"  Categories: {categories}")

    # ---- 2. 切块 ----
    print(f"\n[2/5] Chunking documents...")
    chunker = HybridChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        context_window=3,
    )
    standard_chunks = chunker.split_standard(documents)
    sentence_chunks = chunker.split_sentences(documents)
    print(f"  Standard chunks: {len(standard_chunks)}")
    print(f"  Sentence chunks: {len(sentence_chunks)}")

    # ---- 3. 入库（标准粒度） ----
    print(f"\n[3/5] Adding standard chunks to Chroma...")
    vector_store = VectorStoreManager()
    vector_store.add_documents(standard_chunks)
    count = vector_store.store._collection.count()
    print(f"  Collection: {count} documents")

    # ---- 4. 入库（句子粒度，独立 collection） ----
    print(f"\n[4/5] Adding sentence chunks to Chroma (sentence index)...")
    sentence_store = VectorStoreManager(
        collection_name=f"{settings.chroma_collection_name}_sentences",
    )
    sentence_store.add_documents(sentence_chunks)
    s_count = sentence_store.store._collection.count()
    print(f"  Sentence collection: {s_count} documents")

    # ---- 5. 测试检索 ----
    print(f"\n[5/5] Testing search...")
    test_queries = [
        "How do I reset my API key?",
        "What are the pricing plans?",
        "How to configure SSO with Okta?",
        "Why am I getting a 403 error?",
    ]
    for q in test_queries:
        results = vector_store.search(q, top_k=1)
        if results:
            title = results[0].metadata.get("source", "unknown")
            preview = results[0].page_content[:80].replace("\n", " ")
            print(f"  Q: {q}")
            print(f"  A: [{title}] {preview}...\n")

    print("\nDone! Knowledge base is ready.")
    print(f"  Standard index:   {count} chunks")
    print(f"  Sentence index:   {s_count} chunks")


if __name__ == "__main__":
    main()
