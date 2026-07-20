from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


class Embedder:
    """文本向量化服务 — 支持多供应商切换

    支持的供应商：
    - openai: 通过 OpenAI 兼容接口调用（含阿里百炼、DeepSeek、通义千问）
    - dashscope: 直接调用阿里云 DashScope API
    - local: 本地模型（sentence-transformers）

    使用方式：
        embedder = Embedder(provider="openai")
        vector = embedder.embed_text("你好")
    """

    def __init__(self, provider: str = None, model: str = None):
        from src.config import settings

        self.provider = provider or settings.embedding_provider
        self.model_name = model or settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        """根据 provider 初始化客户端"""
        from src.config import settings

        if self.provider == "dashscope":
            try:
                import dashscope
                dashscope.api_key = settings.dashscope_api_key
                self._client = dashscope
                logger.info("Embedder: DashScope provider initialized")
            except ImportError:
                logger.warning("DashScope not installed, fallback to openai provider")
                self.provider = "openai"
                self._init_client()

        elif self.provider == "local":
            try:
                from sentence_transformers import SentenceTransformer
                self._client = SentenceTransformer(self.model_name)
                logger.info("Embedder: Local model %s loaded", self.model_name)
            except ImportError:
                logger.warning("sentence-transformers not installed, fallback to openai")
                self.provider = "openai"
                self._init_client()

        else:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_api_base,
            )
            logger.info("Embedder: OpenAI-compatible provider initialized")

    def embed_text(self, text: str) -> List[float]:
        """将单条文本转换为向量"""
        if self.provider == "dashscope":
            resp = self._client.TextEmbedding.call(
                model=self.model_name,
                input=text,
                text_type="query" if len(text) < 100 else "document",
            )
            return resp.output["embeddings"][0]["embedding"]

        elif self.provider == "local":
            return self._client.encode(text).tolist()

        else:
            resp = self._client.embeddings.create(
                model=self.model_name,
                input=text,
                dimensions=self.dimensions,
            )
            return resp.data[0].embedding

    def embed_query(self, text: str) -> List[float]:
        """embed_text 的别名，供 Chroma 调用"""
        return self.embed_text(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量将文本转换为向量"""
        if self.provider == "local":
            return [self._client.encode(t).tolist() for t in texts]

        results = []
        for text in texts:
            results.append(self.embed_text(text))
        return results


def create_embedder(provider: str = None, model: str = None) -> Embedder:
    """工厂函数：创建指定 provider 的 Embedder 实例"""
    return Embedder(provider=provider, model=model)
