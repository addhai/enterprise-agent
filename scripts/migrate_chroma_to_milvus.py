#!/usr/bin/env python
"""
Chroma → Milvus 迁移脚本

策略:
  1. 从 Chroma 读取所有文档 + metadata（不读取原始向量，因为 Chroma 不暴露）
  2. 对每个 chunk 重新 Embed（用同一个 Embedder，保证一致性）
  3. 批量写入 Milvus
  4. 双写验证：Chroma 和 Milvus 同时检索 Top-5，对比结果一致性
  5. 验证通过后标记迁移完成

用法:
  # Step 1: 仅迁移（保留 Chroma 不做变更）
  python scripts/migrate_chroma_to_milvus.py --dry-run

  # Step 2: 正式迁移
  python scripts/migrate_chroma_to_milvus.py

  # Step 3: 验证（迁移后对比召回结果）
  python scripts/migrate_chroma_to_milvus.py --verify-only

  # Step 4: 确认无误后，手动清理 Chroma 数据目录
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from langchain_chroma import Chroma

from src.config import settings
from src.rag.embedder import Embedder
from src.rag.milvus_store import MilvusVectorStore, get_milvus_store

logger = logging.getLogger(__name__)


# ---- Query 集合（用于验证） ----
VERIFICATION_QUERIES = [
    "How do I reset my password?",
    "API rate limiting configuration",
    "SSO setup for Okta",
    "Webhook event types",
    "Data export and migration guide",
    "CORS configuration for custom domain",
    "Error code 503 troubleshooting",
]


class ChromaToMilvusMigrator:
    """Chroma → Milvus 数据迁移器"""

    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size
        self.embedder = Embedder()
        self.milvus = MilvusVectorStore()

        # 连接 Chroma（本地文件）
        self.chroma = Chroma(
            collection_name=settings.chroma_collection_name,
            embedding_function=self.embedder,
            persist_directory=settings.chroma_persist_dir,
        )
        logger.info("Chroma loaded: collection=%s, dir=%s",
                    settings.chroma_collection_name, settings.chroma_persist_dir)

    # ------------------------------------------------------------------
    # 读取 Chroma
    # ------------------------------------------------------------------

    def read_chroma(self) -> Tuple[List[str], List[dict], List[List[float]]]:
        """从 Chroma 读取所有文档

        Returns:
            (texts, metadatas, embeddings)
        """
        collection = self.chroma._collection
        result = collection.get(include=["documents", "metadatas", "embeddings"])

        ids = result.get("ids", [])
        texts = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        embeddings = result.get("embeddings", [])

        logger.info("Chroma contains %d documents", len(ids))
        return texts, metadatas, embeddings

    # ------------------------------------------------------------------
    # 写入 Milvus
    # ------------------------------------------------------------------

    def migrate(self, dry_run: bool = False) -> dict:
        """执行迁移

        Returns:
            {"total": N, "success": N, "failed": N, "duration_seconds": float}
        """
        texts, metadatas, _ = self.read_chroma()

        if not texts:
            logger.warning("Chroma is empty, nothing to migrate")
            return {"total": 0, "success": 0, "failed": 0, "duration_seconds": 0}

        if dry_run:
            logger.info("[DRY RUN] Would migrate %d documents to Milvus", len(texts))
            # 打印前 5 条预览
            for i in range(min(5, len(texts))):
                logger.info("  [%d] meta=%s, text=%s...",
                            i, metadatas[i] if i < len(metadatas) else "{}",
                            texts[i][:80])
            return {"total": len(texts), "success": 0, "failed": 0, "duration_seconds": 0, "dry_run": True}

        start = time.time()
        success = 0
        failed = 0

        self.milvus.connect()
        self.milvus.ensure_collection()

        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i:i + self.batch_size]
            batch_metas = metadatas[i:i + self.batch_size] if metadatas else [{}] * len(batch_texts)

            try:
                # 对每批重新 Embed 并插入
                embeddings = [self.embedder.embed_text(t) for t in batch_texts]

                docs = []
                for j, (text, meta, emb) in enumerate(zip(batch_texts, batch_metas, embeddings)):
                    from langchain_core.documents import Document
                    doc = Document(page_content=text, metadata=meta or {})
                    doc.metadata["chunk_id"] = f"{meta.get('doc_id', 'unknown')}:chunk:{j}"
                    doc.metadata["chunk_index"] = i + j
                    docs.append(doc)

                self.milvus.insert(documents=docs, tenant_id="default")
                success += len(batch_texts)
                logger.info("Migrated batch %d-%d (%d/%d)",
                            i, min(i + self.batch_size, len(texts)) - 1,
                            success, len(texts))

            except Exception as e:
                logger.error("Batch %d failed: %s", i, e)
                failed += len(batch_texts)

        duration = time.time() - start

        result = {
            "total": len(texts),
            "success": success,
            "failed": failed,
            "duration_seconds": round(duration, 1),
            "timestamp": datetime.now().isoformat(),
        }

        logger.info("Migration complete: %s", json.dumps(result, indent=2))
        return result

    # ------------------------------------------------------------------
    # 验证
    # ------------------------------------------------------------------

    def verify(self, top_k: int = 5) -> dict:
        """双写验证：对比 Chroma 和 Milvus 的检索结果"""
        results = {
            "queries_tested": 0,
            "queries_passed": 0,
            "queries_failed": 0,
            "details": [],
        }

        for query in VERIFICATION_QUERIES:
            try:
                # Chroma 检索
                chroma_hits = self.chroma.similarity_search_with_relevance_scores(
                    query, k=top_k
                )

                # Milvus 检索
                milvus_hits = self.milvus.search(
                    query_text=query,
                    top_k=top_k,
                    tenant_id="default",
                )

                # 比较文本内容（不是比较分数，因为重 Embed 后分数有微小差异）
                chroma_texts = {doc.page_content[:100] for doc, _ in chroma_hits}
                milvus_texts = {h["text"][:100] for h in milvus_hits}
                overlap = len(chroma_texts & milvus_texts)

                passed = overlap >= top_k * 0.6  # 60% 以上重叠即视为通过

                detail = {
                    "query": query,
                    "chroma_hits": len(chroma_hits),
                    "milvus_hits": len(milvus_hits),
                    "overlap": overlap,
                    "passed": passed,
                }
                results["details"].append(detail)
                results["queries_tested"] += 1

                if passed:
                    results["queries_passed"] += 1
                else:
                    results["queries_failed"] += 1
                    logger.warning("Verification FAILED for query: %s (overlap=%d/%d)",
                                   query, overlap, top_k)

            except Exception as e:
                logger.error("Verification error for query '%s': %s", query[:50], e)
                results["details"].append({"query": query, "error": str(e), "passed": False})
                results["queries_tested"] += 1
                results["queries_failed"] += 1

        results["pass_rate"] = (
            results["queries_passed"] / max(results["queries_tested"], 1)
        )
        results["is_verified"] = results["pass_rate"] >= 0.8

        logger.info("Verification results: %s", json.dumps(results, indent=2, ensure_ascii=False))
        return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Chroma → Milvus 数据迁移工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/migrate_chroma_to_milvus.py --dry-run     # 预览迁移
  python scripts/migrate_chroma_to_milvus.py               # 正式迁移
  python scripts/migrate_chroma_to_milvus.py --verify-only  # 仅验证
        """,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="预览模式，不实际写入")
    parser.add_argument("--verify-only", action="store_true",
                        help="仅执行验证，不迁移")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="每批插入的文档数 (默认 100)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="详细日志")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    migrator = ChromaToMilvusMigrator(batch_size=args.batch_size)

    if args.verify_only:
        result = migrator.verify()
        sys.exit(0 if result["is_verified"] else 1)
    else:
        result = migrator.migrate(dry_run=args.dry_run)

        if not args.dry_run and result["success"] > 0:
            # 迁移后自动验证
            logger.info("Running post-migration verification...")
            verify_result = migrator.verify()
            if not verify_result["is_verified"]:
                logger.warning(
                    "⚠️ Verification PASS RATE = %.0f%% — "
                    "manual review recommended before removing Chroma data",
                    verify_result["pass_rate"] * 100,
                )
                sys.exit(1)

        logger.info("Done.")


if __name__ == "__main__":
    main()
