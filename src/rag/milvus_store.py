"""
Milvus 向量存储适配器 — 替代 Chroma

与现有 VectorStoreManager 接口兼容，同时提供 Milvus 特有功能：
  - 多租户 Partition Key 隔离
  - 标量过滤 + 向量检索 单语句完成
  - 批量写入优化
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    MilvusClient,
    connections,
    utility,
)

from src.config import settings
from src.rag.embedder import Embedder

logger = logging.getLogger(__name__)

# Milvus Collection Schema 常量
COLLECTION_NAME = "knowledge_chunks"
EMBEDDING_DIM = settings.embedding_dimensions  # 1024 (text-embedding-v4)
INDEX_TYPE = "IVF_FLAT"            # 适合百万级，比 HNSW 省内存
METRIC_TYPE = "COSINE"             # 余弦相似度
NLIST = 128                        # IVF 聚类中心数


class MilvusVectorStore:
    """Milvus 向量存储管理器 — 替代 Chroma VectorStoreManager

    使用方式:
        store = MilvusVectorStore()
        store.connect()
        store.ensure_collection()
        store.insert(documents, embeddings)
        results = store.search(query_embedding, top_k=5, filter_expr='tenant_id == "xxx"')
    """

    def __init__(
        self,
        host: str = "milvus-standalone",
        port: int = 19530,
        collection_name: str = COLLECTION_NAME,
    ):
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self._embedder: Optional[Embedder] = None
        self._collection: Optional[Collection] = None
        self._connected = False

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """建立 Milvus 连接"""
        if self._connected:
            return

        try:
            connections.connect(
                alias="default",
                host=self.host,
                port=self.port,
                timeout=10,
            )
            self._connected = True
            logger.info("Connected to Milvus at %s:%d", self.host, self.port)
        except Exception as e:
            logger.error("Failed to connect to Milvus: %s", e)
            raise

    def disconnect(self) -> None:
        """断开连接"""
        if self._connected:
            connections.disconnect("default")
            self._connected = False

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder()
        return self._embedder

    # ------------------------------------------------------------------
    # Collection 管理
    # ------------------------------------------------------------------

    def ensure_collection(self) -> Collection:
        """确保 Collection 存在，不存在则创建

        与 Chroma 不同，Milvus 需要显式定义 Schema。
        每次启动检查，避免重复创建。
        """
        if self._collection is not None:
            return self._collection

        self.connect()

        if utility.has_collection(self.collection_name):
            self._collection = Collection(self.collection_name)
            self._collection.load()  # 加载到内存
            logger.info("Loaded existing Milvus collection: %s (rows=%d)",
                        self.collection_name, self._collection.num_entities)
            return self._collection

        # ---- 定义 Schema ----
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=100,
                        description="Chunk 唯一标识: {doc_id}:chunk:{n}"),
            FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=100,
                        is_partition_key=True,  # 多租户物理隔离
                        description="租户 ID"),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=200,
                        description="源文档 ID"),
            FieldSchema(name="chunk_index", dtype=DataType.INT64,
                        description="切片序号 (从 0 开始)"),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535,
                        description="切片正文"),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM,
                        description="向量嵌入 (1024 维)"),
            FieldSchema(name="metadata_json", dtype=DataType.VARCHAR, max_length=2048,
                        description="元数据 JSON 字符串"),
            FieldSchema(name="access_level", dtype=DataType.VARCHAR, max_length=50,
                        description="文档权限级别: public/internal/confidential/restricted"),
            FieldSchema(name="created_at", dtype=DataType.INT64,
                        description="创建时间戳 (Unix epoch)"),
        ]

        schema = CollectionSchema(
            fields=fields,
            description="Enterprise Agent 知识库切片",
            enable_dynamic_field=False,
        )

        self._collection = Collection(name=self.collection_name, schema=schema)

        # ---- 创建索引 ----
        index_params = {
            "metric_type": METRIC_TYPE,
            "index_type": INDEX_TYPE,
            "params": {"nlist": NLIST},
        }
        self._collection.create_index(
            field_name="embedding",
            index_params=index_params,
            index_name="idx_embedding",
        )

        # ---- 标量索引 (加速过滤) ----
        self._collection.create_index(
            field_name="tenant_id",
            index_name="idx_tenant",
        )
        self._collection.create_index(
            field_name="doc_id",
            index_name="idx_doc",
        )
        self._collection.create_index(
            field_name="access_level",
            index_name="idx_access",
        )

        self._collection.load()
        logger.info("Created new Milvus collection: %s (dim=%d, index=%s)",
                    self.collection_name, EMBEDDING_DIM, INDEX_TYPE)
        return self._collection

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def insert(
        self,
        documents: List[Any],       # List[Document] from langchain
        tenant_id: str = "",
        batch_size: int = 100,
    ) -> int:
        """批量插入文档切片

        Returns:
            插入的行数
        """
        coll = self.ensure_collection()
        embedder = self.embedder

        entities: List[Dict[str, Any]] = []
        for i, doc in enumerate(documents):
            text = doc.page_content if hasattr(doc, "page_content") else str(doc)
            metadata = doc.metadata if hasattr(doc, "metadata") else {}

            chunk_id = metadata.get("chunk_id", f"{metadata.get('doc_id', 'unknown')}:chunk:{i}")

            entities.append({
                "id": chunk_id,
                "tenant_id": tenant_id or metadata.get("tenant_id", "default"),
                "doc_id": metadata.get("doc_id", ""),
                "chunk_index": metadata.get("chunk_index", i),
                "text": text[:65535],  # Milvus VARCHAR 限制
                "embedding": embedder.embed_text(text),
                "metadata_json": self._serialize_metadata(metadata),
                "access_level": metadata.get("access_level", "public"),
                "created_at": int(__import__("time").time()),
            })

        total = 0
        for start in range(0, len(entities), batch_size):
            batch = entities[start:start + batch_size]
            try:
                coll.insert(batch)
                total += len(batch)
            except Exception as e:
                logger.error("Insert batch failed at offset %d: %s", start, e)
                raise

        coll.flush()
        logger.info("Inserted %d chunks into Milvus collection '%s'", total, self.collection_name)
        return total

    def search(
        self,
        query_text: str,
        top_k: int = 5,
        tenant_id: str = "",
        access_levels: Optional[List[str]] = None,
        filter_expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """混合检索：向量相似度 + 标量过滤

        Args:
            query_text: 查询文本
            top_k: 返回 Top-K
            tenant_id: 租户 ID（多租户隔离必传）
            access_levels: 用户允许的权限等级 (如 ["public", "internal"])
            filter_expr: 额外的过滤表达式 (Milvus 语法)

        Returns:
            [{"id": ..., "text": ..., "score": ..., "metadata": ...}, ...]
        """
        coll = self.ensure_collection()
        query_embedding = self.embedder.embed_text(query_text)

        # 构建过滤表达式
        expr_parts = []
        if tenant_id:
            expr_parts.append(f'tenant_id == "{tenant_id}"')
        if access_levels:
            levels = ', '.join(f'"{lvl}"' for lvl in access_levels)
            expr_parts.append(f"access_level in [{levels}]")
        if filter_expr:
            expr_parts.append(filter_expr)

        expr = " and ".join(expr_parts) if expr_parts else None

        search_params = {"metric_type": METRIC_TYPE, "params": {"nprobe": 16}}
        results = coll.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["id", "doc_id", "chunk_index", "text", "metadata_json", "access_level"],
        )

        # 转换 Milvus 结果 → 统一格式
        hits = []
        for result in results:
            for hit in result:
                hits.append({
                    "id": hit.id,
                    "doc_id": hit.entity.get("doc_id", ""),
                    "chunk_index": hit.entity.get("chunk_index", 0),
                    "text": hit.entity.get("text", ""),
                    "score": hit.distance,  # COSINE 下 1 = 最相似
                    "metadata": self._deserialize_metadata(hit.entity.get("metadata_json", "{}")),
                    "access_level": hit.entity.get("access_level", "public"),
                })

        return hits

    def delete_by_doc(self, doc_id: str) -> int:
        """按文档 ID 删除所有关联切片"""
        coll = self.ensure_collection()
        expr = f'doc_id == "{doc_id}"'
        result = coll.delete(expr)
        logger.info("Deleted %s chunks for doc_id=%s", result.delete_count, doc_id)
        return result.delete_count

    def delete_by_tenant(self, tenant_id: str) -> int:
        """按租户 ID 删除所有数据"""
        coll = self.ensure_collection()
        expr = f'tenant_id == "{tenant_id}"'
        result = coll.delete(expr)
        logger.info("Deleted %s chunks for tenant_id=%s", result.delete_count, tenant_id)
        return result.delete_count

    def count(self) -> int:
        """总切片数"""
        coll = self.ensure_collection()
        return coll.num_entities

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_metadata(metadata: dict) -> str:
        """将 metadata dict 序列化为 JSON 字符串"""
        import json
        safe = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool, type(None))):
                safe[k] = v
            elif isinstance(v, (list, dict)):
                try:
                    safe[k] = json.dumps(v, ensure_ascii=False)
                except Exception:
                    safe[k] = str(v)[:500]
            else:
                safe[k] = str(v)[:500]
        return json.dumps(safe, ensure_ascii=False)

    @staticmethod
    def _deserialize_metadata(json_str: str) -> dict:
        """将 JSON 字符串反序列化为 metadata dict"""
        import json
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return {"raw": json_str}


# ---------------------------------------------------------------------------
# 全局单例 (替代 chroma_data 目录)
# ---------------------------------------------------------------------------
_milvus_store: Optional[MilvusVectorStore] = None


def get_milvus_store() -> MilvusVectorStore:
    """获取全局 Milvus 向量存储实例"""
    global _milvus_store
    if _milvus_store is None:
        _milvus_store = MilvusVectorStore()
        _milvus_store.ensure_collection()
        logger.info("Milvus vector store initialized")
    return _milvus_store
