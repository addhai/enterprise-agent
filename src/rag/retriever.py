from typing import List, Tuple
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from src.rag.vector_store import VectorStoreManager


class HybridRetriever:
    """混合检索器：向量检索 + BM25 关键词检索 + RRF 融合"""

    def __init__(self, persist_directory: str = None, collection_name: str = None):
        self.vector_store = VectorStoreManager(
            persist_directory=persist_directory,
            collection_name=collection_name
        )
        self.bm25_retriever: BM25Retriever = None
        self._all_documents: List[Document] = []

    def index_documents(self, documents: List[Document]) -> None:
        """索引文档：同时写入向量库和 BM25"""
        self._all_documents = documents
        self.vector_store.add_documents(documents)
        self.bm25_retriever = BM25Retriever.from_documents(documents)

    def search(self, query: str, top_k: int = 5) -> List[Document]:
        """混合检索，返回去重合并后的结果"""
        return self.search_with_scores(query, top_k)

    def search_with_scores(self, query: str, top_k: int = 5) -> List[Tuple[Document, float]]:
        """带分数的混合检索"""
        # 向量检索
        vector_results = self.vector_store.search_with_scores(query, top_k=top_k * 2)

        # BM25 检索
        bm25_results = []
        if self.bm25_retriever:
            bm25_docs = self.bm25_retriever.invoke(query)
            bm25_results = [(doc, 1.0 - i * 0.05) for i, doc in enumerate(bm25_docs[:top_k * 2])]

        # RRF 融合
        merged = self._rrf_fusion(vector_results, bm25_results, top_k)
        return merged

    def _rrf_fusion(
        self,
        vector_results: List[Tuple[Document, float]],
        bm25_results: List[Tuple[Document, float]],
        top_k: int,
        k: int = 60
    ) -> List[Tuple[Document, float]]:
        """Reciprocal Rank Fusion — 合并两组检索结果"""
        scores = {}
        doc_map = {}

        # 向量检索排名
        for rank, (doc, _) in enumerate(vector_results):
            doc_id = doc.page_content[:100]  # 用内容前100字符做 key
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
            doc_map[doc_id] = doc

        # BM25 排名
        for rank, (doc, _) in enumerate(bm25_results):
            doc_id = doc.page_content[:100]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
            doc_map[doc_id] = doc

        # 按 RRF 分数排序
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        return [(doc_map[doc_id], scores[doc_id]) for doc_id in sorted_ids[:top_k]]

    def delete_collection(self) -> None:
        """清理向量库"""
        self.vector_store.delete_collection()
        self.bm25_retriever = None
        self._all_documents = []
