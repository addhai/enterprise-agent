from typing import List

import logging

from langchain_core.documents import Document
from src.config import settings
from src.rag.embedder import Embedder

logger = logging.getLogger(__name__)


class VectorStoreManager:
    """向量数据库管理器 — 支持 Chroma / Milvus / auto 模式

    auto 模式：优先尝试 Milvus，连接失败则降级到 Chroma
    """

    def __init__(self, persist_directory: str = None, collection_name: str = None):
        self.persist_directory = persist_directory or settings.chroma_persist_dir
        self.collection_name = collection_name or settings.chroma_collection_name
        self._embedding_function = Embedder()
        self._store = None
        self._backend = None          # "chroma" | "milvus"
        self._milvus_store = None     # MilvusVectorStore 实例

    def _init_store(self):
        """根据配置初始化向量库"""
        backend = settings.vector_store_backend

        if backend in ("milvus", "auto"):
            # 尝试连接 Milvus
            try:
                from src.rag.milvus_store import MilvusVectorStore
                self._milvus_store = MilvusVectorStore()
                self._milvus_store.connect()
                self._milvus_store.ensure_collection()
                self._backend = "milvus"
                logger.info("Using Milvus vector store at %s:%d", self._milvus_store.host, self._milvus_store.port)
                return
            except Exception as e:
                if backend == "milvus":
                    logger.error("Milvus connection failed: %s", e)
                    raise
                logger.warning("Milvus unavailable (%s), falling back to Chroma", e)

        # Chroma 降级 / 默认
        from langchain_chroma import Chroma
        self._store = Chroma(
            collection_name=self.collection_name,
            embedding_function=self._embedding_function,
            persist_directory=self.persist_directory,
        )
        self._backend = "chroma"
        logger.info("Using Chroma vector store at %s", self.persist_directory)

    @property
    def store(self):
        """延迟初始化向量库"""
        if self._store is None and self._milvus_store is None:
            self._init_store()
        return self._store

    @property
    def backend(self) -> str:
        """当前使用的后端"""
        if self._backend is None:
            self._init_store()
        return self._backend

    def add_documents(self, documents: List[Document]) -> List[str]:
        """添加文档到向量库"""
        if not documents:
            return []

        if self.backend == "milvus":
            count = self._milvus_store.insert(documents)
            return [str(i) for i in range(count)]

        return self.store.add_documents(documents)

    def search(self, query: str, top_k: int = None) -> List[Document]:
        """向量相似度搜索"""
        k = top_k or settings.retrieval_top_k

        if self.backend == "milvus":
            results = self._milvus_store.search(query, top_k=k)
            return [
                Document(page_content=r["text"], metadata=r.get("metadata", {}))
                for r in results
            ]

        if self.store._collection.count() == 0:
            return []
        return self.store.similarity_search(query, k=k)

    def search_with_scores(self, query: str, top_k: int = None) -> List[tuple]:
        """带相似度分数的搜索"""
        k = top_k or settings.retrieval_top_k

        if self.backend == "milvus":
            results = self._milvus_store.search(query, top_k=k)
            return [
                (Document(page_content=r["text"], metadata=r.get("metadata", {})), r["score"])
                for r in results
            ]

        if self.store._collection.count() == 0:
            return []
        return self.store.similarity_search_with_relevance_scores(query, k=k)

    def delete_collection(self) -> None:
        """删除整个集合（测试用）"""
        if self.backend == "milvus" and self._milvus_store:
            # Milvus 删除 collection
            from pymilvus import utility
            utility.drop_collection(self._milvus_store.collection_name)
            self._milvus_store._collection = None
        elif self._store:
            self._store.delete_collection()

    def delete_by_ids(self, ids: List[str]) -> int:
        """按 ID 删除文档（幂等）"""
        if not ids:
            return 0

        if self.backend == "milvus":
            # Milvus 按表达式删除
            from pymilvus import Collection
            coll = self._milvus_store.ensure_collection()
            id_list = ', '.join(f'"{i}"' for i in ids)
            result = coll.delete(f'id in [{id_list}]')
            return result.delete_count

        try:
            self.store._collection.delete(ids=ids)
            return len(ids)
        except Exception:
            return 0

    def count(self) -> int:
        """返回集合中的文档数"""
        if self.backend == "milvus":
            return self._milvus_store.count()
        if self._store:
            return self.store._collection.count()
        return 0
