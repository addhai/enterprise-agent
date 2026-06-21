from typing import List
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from src.config import settings


class VectorStoreManager:
    """Chroma 向量数据库管理器"""

    def __init__(self, persist_directory: str = None, collection_name: str = None):
        self.persist_directory = persist_directory or settings.chroma_persist_dir
        self.collection_name = collection_name or settings.chroma_collection_name
        self._embedding_function = OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.openai_api_key,
        )
        self._store = None

    @property
    def store(self):
        """延迟初始化向量库"""
        if self._store is None:
            self._store = Chroma(
                collection_name=self.collection_name,
                embedding_function=self._embedding_function,
                persist_directory=self.persist_directory,
            )
        return self._store

    def add_documents(self, documents: List[Document]) -> None:
        """添加文档到向量库"""
        if not documents:
            return
        self.store.add_documents(documents)

    def search(self, query: str, top_k: int = None) -> List[Document]:
        """向量相似度搜索"""
        k = top_k or settings.retrieval_top_k
        if self.store._collection.count() == 0:
            return []
        return self.store.similarity_search(query, k=k)

    def search_with_scores(self, query: str, top_k: int = None) -> List[tuple]:
        """带相似度分数的搜索"""
        k = top_k or settings.retrieval_top_k
        if self.store._collection.count() == 0:
            return []
        return self.store.similarity_search_with_relevance_scores(query, k=k)

    def delete_collection(self) -> None:
        """删除整个集合（测试用）"""
        if self._store:
            self._store.delete_collection()
