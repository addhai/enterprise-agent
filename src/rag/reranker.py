"""重排序模型 — 在 RRF 融合后对候选结果二次排序

参考：RAGFlow 的 rerank_model.py（抽象基类 + 多 Provider）
对齐阿里云百炼：使用 gte-rerank 模型对检索结果重排序

三种 Provider：
    1. DashscopeReranker: 调用阿里云百炼 gte-rerank 接口（推荐）
    2. LocalBgeReranker: 本地 BGE-reranker 模型（需安装 sentence-transformers）
    3. LLMReranker: 用 LLM 对每个文档打分（降级方案，无需额外依赖）

工作流程：
    检索召回 → RRF 融合 → **重排序** → 权限过滤 → 返回 top_n

归一化：
    所有 Provider 输出分数均归一化到 [0, 1]，与 RAGFlow 保持一致
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import List, Tuple

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class BaseReranker(ABC):
    """重排序模型抽象基类

    所有子类必须实现 _compute_scores，返回每个文档的相关性分数。
    基类负责空输入处理和分数归一化到 [0, 1]。
    """

    def __init__(self, model_name: str = "", **kwargs):
        self.model_name = model_name

    def rerank(
        self,
        query: str,
        documents: List[Tuple[Document, float]],
        top_n: int = 5,
    ) -> List[Tuple[Document, float]]:
        """对文档重排序，返回 top_n 个结果

        Args:
            query: 查询文本
            documents: 候选文档列表 [(doc, original_score), ...]
            top_n: 返回前 N 个结果

        Returns:
            重排序后的列表 [(doc, new_score), ...]，分数已归一化到 [0, 1]
        """
        if not query or not documents:
            return documents[:top_n]

        # 提取文档文本
        texts = [doc.page_content for doc, _ in documents]

        try:
            scores = self._compute_scores(query, texts)
        except Exception as e:
            logger.warning(
                "Rerank failed (%s: %s), falling back to original order",
                self.__class__.__name__, e,
            )
            return documents[:top_n]

        # 归一化到 [0, 1]
        scores = self._normalize(scores)

        # 按新分数排序
        reranked = list(zip([doc for doc, _ in documents], scores))
        reranked.sort(key=lambda x: x[1], reverse=True)

        logger.debug(
            "Rerank %s: %d candidates → top %d (max_score=%.4f)",
            self.__class__.__name__, len(documents), min(top_n, len(reranked)),
            reranked[0][1] if reranked else 0.0,
        )

        return reranked[:top_n]

    @abstractmethod
    def _compute_scores(self, query: str, texts: List[str]) -> List[float]:
        """Provider 特定打分逻辑，返回原始分数（将被归一化）"""
        raise NotImplementedError

    @staticmethod
    def _normalize(scores: List[float]) -> List[float]:
        """将分数归一化到 [0, 1]（参考 RAGFlow 的 _normalize_rank）

        - 已经在 [0, 1] 范围内的分数保持不变
        - 超出范围的分数 min-max 归一化
        - 无差异的分数（如单一候选）截断到 [0, 1]
        """
        if not scores:
            return scores

        min_s = min(scores)
        max_s = max(scores)

        if min_s >= 0.0 and max_s <= 1.0:
            return scores

        span = max_s - min_s
        if span < 1e-3:
            return [max(0.0, min(1.0, s)) for s in scores]

        return [(s - min_s) / span for s in scores]


class DashscopeReranker(BaseReranker):
    """阿里云百炼 gte-rerank 重排序模型

    通过 OpenAI 兼容接口调用，需要配置 openai_api_key。
    模型默认 gte-rerank，对中英文均支持良好。

    配置：
        RERANK_PROVIDER=dashscope
        RERANK_MODEL=gte-rerank
        OPENAI_API_KEY=sk-xxx
    """

    def __init__(self, api_key: str, model_name: str = "gte-rerank",
                 api_base: str = "", timeout: float = 10.0):
        super().__init__(model_name)
        self.api_key = api_key
        self.api_base = api_base or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.timeout = timeout

    def _compute_scores(self, query: str, texts: List[str]) -> List[float]:
        import json
        import urllib.request

        payload = {
            "model": self.model_name,
            "query": query,
            "documents": texts,
            "top_n": len(texts),
            "return_documents": False,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.api_base}/rerank",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310  # URL 来自受信任配置(self.api_base)，非用户输入
            body = json.loads(resp.read().decode("utf-8"))

        # 阿里云 gte-rerank 返回格式: {"results": [{"index": 0, "relevance_score": 0.95}, ...]}
        results = body.get("results", [])
        # 按 index 对齐分数
        scores = [0.0] * len(texts)
        for r in results:
            idx = r.get("index", 0)
            if idx < len(scores):
                scores[idx] = r.get("relevance_score", 0.0)
        return scores


class LocalBgeReranker(BaseReranker):
    """本地 BGE-reranker 模型

    使用 sentence-transformers 加载 BAAI/bge-reranker-base 模型。
    首次加载需下载模型（约 1GB），后续走本地缓存。

    优点：无 API 调用成本、低延迟
    缺点：占用内存、首次下载慢

    配置：
        RERANK_PROVIDER=local_bge
        RERANK_MODEL=BAAI/bge-reranker-base
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        super().__init__(model_name)
        self._model = None

    @property
    def model(self):
        """懒加载模型"""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
            logger.info("BGE reranker loaded: %s", self.model_name)
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )
        return self._model

    def _compute_scores(self, query: str, texts: List[str]) -> List[float]:
        # CrossEncoder 预测 (query, text) 对的相关性
        pairs = [[query, text] for text in texts]
        scores = self.model.predict(pairs).tolist()
        return scores


class LLMReranker(BaseReranker):
    """LLM 降级重排序器

    用 LLM 对每个文档打分（0-10），降级方案，无需额外依赖。
    适用于：未配置阿里云 API、本地模型不可用的场景。

    成本较高：N 个文档需 N 次 LLM 调用（或一次批量调用）
    适合：候选数较少（<10）的场景

    配置：
        RERANK_PROVIDER=llm
        RERANK_MODEL=qwen-plus（使用 LLM 模型打分）
    """

    def __init__(self, llm=None, model_name: str = "qwen-plus"):
        super().__init__(model_name)
        self.llm = llm

    def _compute_scores(self, query: str, texts: List[str]) -> List[float]:
        if not self.llm:
            # 无 LLM 可用时，按文档长度作为简单启发式分数
            logger.warning("LLMReranker: no LLM available, using length heuristic")
            return [float(len(t)) for t in texts]

        scores = []
        for text in texts:
            prompt = (
                "你是检索结果相关性评估专家。请评估以下文档对查询的相关性，"
                "只返回一个 0 到 10 的数字（10 表示完全相关，0 表示无关）。\n\n"
                f"查询：{query}\n\n"
                f"文档：{text[:500]}\n\n"
                "相关性分数（0-10）："
            )
            try:
                response = self.llm.invoke(prompt)
                # 提取数字
                content = response.content if hasattr(response, "content") else str(response)
                import re
                match = re.search(r"(\d+(?:\.\d+)?)", content)
                score = float(match.group(1)) if match else 5.0
                scores.append(score / 10.0)  # 归一化到 0-1
            except Exception as e:
                logger.warning("LLM scoring failed: %s, using default", e)
                scores.append(0.5)
        return scores


def create_reranker(provider: str, **kwargs) -> BaseReranker:
    """工厂函数：根据 provider 名称创建重排序器

    Args:
        provider: Provider 名称 (dashscope / local_bge / llm)
        **kwargs: 传递给具体 Reranker 的参数

    Returns:
        BaseReranker 实例

    Raises:
        ValueError: 不支持的 provider
    """
    provider = provider.lower().strip()

    if provider == "dashscope":
        api_key = kwargs.get("api_key") or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "DashscopeReranker requires OPENAI_API_KEY. "
                "Set it in .env or use another provider."
            )
        return DashscopeReranker(
            api_key=api_key,
            model_name=kwargs.get("model_name", "gte-rerank"),
            api_base=kwargs.get("api_base", ""),
            timeout=kwargs.get("timeout", 10.0),
        )

    if provider == "local_bge":
        return LocalBgeReranker(
            model_name=kwargs.get("model_name", "BAAI/bge-reranker-base"),
        )

    if provider == "llm":
        return LLMReranker(
            llm=kwargs.get("llm"),
            model_name=kwargs.get("model_name", "qwen-plus"),
        )

    raise ValueError(
        f"Unsupported rerank provider: {provider}. "
        f"Supported: dashscope / local_bge / llm"
    )
