from typing import List
from langchain_openai import OpenAIEmbeddings
from src.config import settings


class Embedder:
    """文本向量化服务，封装 OpenAI Embedding API"""

    def __init__(self, model: str = None):
        self.model_name = model or settings.embedding_model
        self._client = OpenAIEmbeddings(
            model=self.model_name,
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
            dimensions=settings.embedding_dimensions,
        )

    def embed_text(self, text: str) -> List[float]:
        """将单条文本转换为向量"""
        return self._client.embed_query(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量将文本转换为向量"""
        return self._client.embed_documents(texts)
