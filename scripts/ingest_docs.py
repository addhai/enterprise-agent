#!/usr/bin/env python
"""将 data/docs/ 下的所有文档加载、切块、入库到 Chroma"""

import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag.loader import DocumentLoader
from src.rag.chunker import DocumentChunker
from src.rag.vector_store import VectorStoreManager
from src.config import settings


def main():
    print("=" * 50)
    print("CloudSync Knowledge Base Ingestion")
    print("=" * 50)

    # 1. 加载文档
    docs_dir = Path(__file__).parent.parent / "data" / "docs"
    print(f"\n[1/3] Loading documents from {docs_dir}...")
    loader = DocumentLoader()
    documents = loader.load_directory(str(docs_dir))
    print(f"  Loaded {len(documents)} document(s)")

    # 2. 切块
    print(f"\n[2/3] Chunking documents (size={settings.chunk_size}, overlap={settings.chunk_overlap})...")
    chunker = DocumentChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap
    )
    chunks = chunker.split(documents)
    print(f"  Created {len(chunks)} chunks")

    # 3. 入库
    print(f"\n[3/3] Adding to Chroma collection '{settings.chroma_collection_name}'...")
    vector_store = VectorStoreManager()
    vector_store.add_documents(chunks)

    count = vector_store.store._collection.count()
    print(f"  Collection now has {count} documents")
    print(f"\nDone! Knowledge base is ready.")

    # 测试检索
    print("\n--- Test Search ---")
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


if __name__ == "__main__":
    main()
