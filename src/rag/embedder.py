from typing import List
from openai import OpenAI
from src.config import settings


class Embedder:
    """文本向量化服务，直接调用阿里百炼 DashScope Embedding API"""

    def __init__(self, model: str = None):
        self.model_name = model or settings.embedding_model
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
        )

    def embed_text(self, text: str) -> List[float]:
        """将单条文本转换为向量"""
        resp = self._client.embeddings.create(
            model=self.model_name,
            input=text,
            dimensions=settings.embedding_dimensions,
        )
        return resp.data[0].embedding

    def embed_query(self, text: str) -> List[float]:
        """embed_text 的别名，供 Chroma 调用"""
        return self.embed_text(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量将文本转换为向量（逐条调用，避免 LangChain tokenize 兼容问题）"""
        results = []
        for text in texts:
            resp = self._client.embeddings.create(
                model=self.model_name,
                input=text,
                dimensions=settings.embedding_dimensions,
            )
            results.append(resp.data[0].embedding)
        return results
