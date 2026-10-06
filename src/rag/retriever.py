"""混合检索器：向量检索 + BM25 关键词检索 + RRF 融合

v0.3 更新（2026-07-01）：
    - 句子窗口检索：命中句子后自动展开前后 N 句上下文
    - 双索引支持：标准粒度 + 句子粒度并行检索
    - 元数据过滤：可按 source/category/page 过滤
    - 版本冲突处理：按发布时间/生效状态排序，废弃版本不参与生成，冲突时提示用户

v0.4 更新（2026-07-02）：
    - 版本冲突检测：同一问题召回多个版本时自动排序 + 废弃过滤
    - 冲突提示：当同一主题有多个活跃版本时，在 metadata 中标注 conflict

v0.5 更新（2026-07-15）：
    - 多后端支持：Chrom | Milvus，通过 vector_store_backend 配置切换
    - 远程 RAG Service 调用：可选的 HTTP 调用 rag-service
    - 自动降级：Milvus 不可用时降级到 Chroma
"""

from __future__ import annotations

import contextlib
import logging
import re
import time

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from src.config import settings
from src.rag.chunker import SentenceWindowSplitter
from src.rag.vector_store import VectorStoreManager

logger = logging.getLogger(__name__)


class HybridRetriever:
    """混合检索器

    双索引架构：
        standard_store:  段落级索引（适合长文段、配置步骤）
        sentence_store:  句子级索引（适合 FAQ、错误码、精确匹配）

    检索策略：
        1. 两路并行检索 → RRF 融合 → 去重
        2. 命中句子级结果时，自动展开前后 N 句上下文
        3. 可选按 source/category/page 过滤
    """

    def __init__(
        self,
        persist_directory: str = None,
        collection_name: str = None,
        context_window: int = 3,
        backend: str = None,  # "chroma" | "milvus" | "auto" | "remote"
        rag_service_url: str = None,
    ):
        self.context_window = context_window
        self.sentence_splitter = SentenceWindowSplitter(
            context_window=context_window,
        )

        # ---- 后端选择 ----
        self.backend = backend or settings.vector_store_backend
        self.rag_service_url = rag_service_url or settings.rag_service_url

        # Milvus 客户端 (懒加载)
        self._milvus_store = None

        # 标准粒度索引 (Chroma)
        self.vector_store = VectorStoreManager(
            persist_directory=persist_directory,
            collection_name=collection_name,
        )

        # 句子粒度索引（独立 collection）— 仅 Chroma 模式
        self.sentence_store = (
            VectorStoreManager(
                persist_directory=persist_directory,
                collection_name=f"{collection_name}_sentences",
            )
            if collection_name and self.backend != "remote"
            else None
        )

        self.bm25_retriever: BM25Retriever = None
        self._all_documents: list[Document] = []

        # 多知识库权重映射（对齐阿里云百炼，范围 0.5~2，默认 1.0）
        self._kb_weights_map: dict[str, float] = self._parse_kb_weights(
            settings.kb_weights
        )
        # 文档级权重表（按文件名加权，缓存到 _doc_weights_cache）
        self._doc_weights_cache: dict[str, float] = {}

        # 重排序器（懒加载，对齐阿里云百炼 + RAGFlow）
        self._reranker = None
        # ⚠️ 不要在这里把 settings 的值拷进实例属性。
        # 拷贝 = 构造时快照 = 假热更新：配置中心改了 rerank_enabled，行为不变。
        # 正确做法是访问时读（见下面 _rerank_enabled / _rerank_top_n 两个 property）。
        # 初始化失败闩锁：一旦重排序器创建失败就置位，避免每次检索都白跑一次
        # 注定失败的初始化。置位后开关恒为关闭，需重启进程才能恢复（有意为之）。
        self._rerank_init_failed = False

        logger.info(
            "HybridRetriever initialized: backend=%s, rag_url=%s, rerank=%s",
            self.backend,
            self.rag_service_url if self.backend == "remote" else "N/A",
            self._rerank_enabled,
        )

    @property
    def _rerank_enabled(self) -> bool:
        """重排序开关（每次访问都实时读配置）

        为什么要用 property 而不是实例属性：
            配置中心支持热更新 rerank_enabled。若在 __init__ 里拷贝成实例属性，
            改配置后检索行为不变（假热更新），只能重启进程。这里读时取值，
            改完立即生效。初始化失败闩锁优先：闩锁置位后恒为 False。
        """
        if getattr(self, "_rerank_init_failed", False):
            return False
        return bool(getattr(settings, "rerank_enabled", False))

    @property
    def _rerank_top_n(self) -> int:
        """重排序返回条数（同样读时取值，理由同上）"""
        return int(getattr(settings, "rerank_top_n", 5) or 5)

    @staticmethod
    def _parse_kb_weights(raw: str) -> dict[str, float]:
        """解析 kb_weights 配置（JSON 字符串 → dict）

        示例: '{"kb_a": 1.0, "kb_b": 1.5}' → {"kb_a": 1.0, "kb_b": 1.5}
        权重范围限制在 0.5~2.0，超出则截断。空字符串返回空 dict。
        """
        if not raw or not raw.strip():
            return {}
        try:
            import json

            data = json.loads(raw)
            if not isinstance(data, dict):
                return {}
            # 截断到 0.5~2.0 范围（对齐阿里云）
            return {str(k): max(0.5, min(2.0, float(v))) for k, v in data.items()}
        except (ValueError, TypeError):
            logger.warning("Invalid kb_weights config, ignored: %s", raw)
            return {}

    @staticmethod
    def _parse_doc_weights(raw: str) -> dict[str, float] | None:
        """解析文档级权重配置，支持两种等价写法

        1. JSON（settings 默认值口径）：
               '{"fault_troubleshooting_manual.md": 1.5, "faq_full.md": 0.8}'
        2. 逗号简写（.env 与部署文档的长期既有口径）：
               'fault_troubleshooting_manual.md:1.5,faq_full.md:0.8'

        历史背景：.env.production 与 .env.production.example 一直发逗号简写，
        旧解析器只认 JSON，导致生产日志反复 `Invalid doc_weights config, ignored`，
        文档权重长期静默失效。两种写法现在等价。

        权重范围 0.5~2.0，超出截断；空白条目（尾随逗号）容忍跳过。
        任一非空条目非法（缺冒号/权重不是数字）整体判失效返回 None，
        由调用方告警并按空表处理，避免半份配置静默生效。
        """
        if not raw or not str(raw).strip():
            return {}

        text = str(raw).strip()
        try:
            import json

            data = json.loads(text)
            if not isinstance(data, dict):
                return None
            return {str(k): max(0.5, min(2.0, float(v))) for k, v in data.items()}
        except (ValueError, TypeError):
            pass  # 不是 JSON，走逗号简写

        pairs: dict[str, float] = {}
        for chunk in text.split(","):
            item = chunk.strip()
            if not item:
                continue
            if ":" not in item:
                return None
            name, _, value = item.rpartition(":")
            name = name.strip()
            value = value.strip()
            if not name:
                return None
            try:
                pairs[name] = max(0.5, min(2.0, float(value)))
            except ValueError:
                return None

        return pairs or None

    def _get_doc_weights_map(self) -> dict[str, float]:
        """解析文档级权重表（settings.doc_weights → dict），带进程内缓存

        与 _parse_kb_weights 的区别：
            kb_weights    按知识库 id（kb_id）加权，粒度粗
            doc_weights   按文档文件名（metadata["source"]）加权，粒度细
        两者在 RRF 融合中相乘，共同决定最终分数。

        为什么要缓存（_doc_weights_cache）：
            每次检索都对同一份配置做解析是纯浪费；配置热更新由配置中心
            负责，不走这里。缓存为空 dict 时才解析，非空直接返回同一对象，
            调用方可依赖 `w1 is w2` 判断命中缓存。

        权重范围 0.5~2.0，非法配置告警后按空表处理（调用方按 1.0 兜底）。
        """
        if self._doc_weights_cache:
            return self._doc_weights_cache

        raw = getattr(settings, "doc_weights", "")
        parsed = self._parse_doc_weights(raw)
        if parsed is None:
            logger.warning("Invalid doc_weights config, ignored: %s", raw)
            parsed = {}
        self._doc_weights_cache = parsed
        return self._doc_weights_cache

    def _get_doc_weight(self, doc: Document) -> float:
        """获取单篇文档的权重（按 metadata["source"] 匹配）

        未配置权重的文档默认 1.0（权重表为空时全部 1.0，等价于不加权）。
        """
        weights = self._get_doc_weights_map()
        if not weights:
            return 1.0
        source = doc.metadata.get("source", "")
        if not source:
            return 1.0
        return weights.get(source, 1.0)

    def _source_chunk_cap(self) -> int:
        """单个来源（同一文件）最多贡献多少条结果

        取值规则（顺序即优先级）：
            settings.retrieval_source_cap 存在且为正整数 → 原值
            值 <= 0（0 会把结果整体截空，属配置事故）→ 夹到 1
            值非数字 / 属性缺失 → 兜底默认 2
        """
        raw = getattr(settings, "retrieval_source_cap", 2)
        try:
            cap = int(raw)
        except (ValueError, TypeError):
            logger.warning("Invalid retrieval_source_cap=%r, fallback to 2", raw)
            return 2
        if cap < 1:
            logger.warning("retrieval_source_cap=%d 会把结果截空，已夹到 1", cap)
            return 1
        return cap

    # ------------------------------------------------------------------
    # Milvus 懒加载 + 降级
    # ------------------------------------------------------------------

    @property
    def milvus_store(self):
        """懒加载 Milvus 连接，自动降级"""
        if self._milvus_store is not None:
            return self._milvus_store

        try:
            from src.rag.milvus_store import MilvusVectorStore

            self._milvus_store = MilvusVectorStore(
                host=settings.milvus_host,
                port=settings.milvus_port,
            )
            self._milvus_store.ensure_collection()
            logger.info(
                "Milvus store initialized (host=%s:%d)",
                settings.milvus_host,
                settings.milvus_port,
            )
        except Exception as e:
            logger.warning("Milvus unavailable (%s), falling back to Chroma", e)
            self._milvus_store = None
            self.backend = "chroma"  # 降级
        return self._milvus_store

    @property
    def _use_milvus(self) -> bool:
        return self.backend in ("milvus", "auto") and self.milvus_store is not None

    @property
    def _use_remote(self) -> bool:
        return self.backend == "remote" and bool(self.rag_service_url)

    def index_documents(self, documents: list[Document]) -> None:
        """索引文档：同时写入向量库和 BM25

        注意：此方法只索引标准粒度。
        句子粒度需要在外部通过 HybridChunker.split_both() 获取后单独索引。
        """
        self._all_documents = documents
        self.vector_store.add_documents(documents)
        self.bm25_retriever = BM25Retriever.from_documents(documents)

    def add_documents(self, documents: list[Document], tenant_id: str = "") -> None:
        """增量索引文档（知识库 API 单文档入库用）

        与 index_documents 不同，本方法不清空既有索引：
            1. 为缺失 tenant_id 的 chunk 补上 tenant_id
            2. 增量写入向量库（Chroma 持久化，重启不丢）
            3. 从累积的 self._all_documents 重建 BM25，保持与向量库一致
        """
        if not documents:
            return
        # 空 tenant_id 统一归为 "default"，与 _rbac_filter 规则一致
        effective_tenant = tenant_id or "default"
        for doc in documents:
            if not doc.metadata.get("tenant_id"):
                doc.metadata["tenant_id"] = effective_tenant
        self.vector_store.add_documents(documents)
        self._all_documents.extend(documents)
        try:
            self.bm25_retriever = BM25Retriever.from_documents(self._all_documents)
        except Exception as e:
            logger.warning("BM25 rebuild failed (non-fatal): %s", e)

    def index_sentence_chunks(self, sentence_chunks: list[Document]) -> None:
        """索引句子级 chunk（由 HybridChunker.split_sentences() 产出）"""
        if self.sentence_store:
            self.sentence_store.add_documents(sentence_chunks)
            logger.info("Indexed %d sentence chunks", len(sentence_chunks))

    def search(
        self,
        query: str,
        top_k: int = 5,
        expand_context: bool = True,
        filter_by: dict | None = None,
        user_id: str = "",
        tenant_id: str = "",
        user_access_levels: list[str] | None = None,
    ) -> list[Document]:
        """混合检索，返回去重合并后的结果

        Args:
            query: 查询文本
            top_k: 返回结果数量
            expand_context: 是否展开句子级结果的上下文
            filter_by: 元数据过滤 {source: "xxx", category: "markdown", ...}
            user_id: 当前用户 ID
            tenant_id: 当前租户 ID（多租户隔离）
            user_access_levels: 用户拥有的权限等级列表，如 ["public", "internal"]
                                默认从 loader 的 AccessLevel 导入

        Returns:
            Document 列表，每个文档的 metadata 可能包含：
                - version_conflicts: 冲突提示信息列表
                - has_conflicts: 是否有版本冲突 (bool)
                - access_filtered: 被权限过滤掉的文档数
        """
        results = self.search_with_scores(
            query,
            top_k,
            expand_context,
            filter_by,
            user_id=user_id,
            tenant_id=tenant_id,
            user_access_levels=user_access_levels,
        )
        return [doc for doc, _ in results]

    def search_with_scores(
        self,
        query: str,
        top_k: int = 5,
        expand_context: bool = True,
        filter_by: dict | None = None,
        user_id: str = "",
        tenant_id: str = "",
        user_access_levels: list[str] | None = None,
    ) -> list[tuple[Document, float]]:
        """带分数的混合检索

        权限过滤流程：
            1. 混合检索 → 召回 top_k*2 个候选
            2. 租户隔离过滤：tenant_id 不匹配的排除
            3. 权限等级过滤：用户 access_level 不包含文档的排除
            4. 版本冲突处理：同一问题多版本 → 保留最新活跃版
            5. 截断到 top_k
        """
        # 默认权限等级：public 所有人都可见
        if user_access_levels is None:
            user_access_levels = ["public", "internal", "confidential", "restricted"]

        # 检索耗时计时起点（Prometheus rag_search_duration_seconds）
        _rag_t0 = time.perf_counter()

        # 标准粒度：向量检索
        vector_results = self._vector_search(query, top_k * 2, filter_by)

        # 标准粒度：BM25
        bm25_results = self._bm25_search(query, top_k * 2, filter_by)

        # 句子粒度：向量检索
        sentence_results = (
            self._sentence_vector_search(query, top_k, filter_by)
            if self.sentence_store
            else []
        )

        # RRF 融合（标准粒度）
        standard_merged = self._rrf_fusion(vector_results, bm25_results, top_k)

        # 句子粒度结果：展开上下文
        if expand_context and sentence_results:
            expanded = []
            for doc, score in sentence_results:
                expanded_doc = self.sentence_splitter.expand_context(doc)
                expanded.append((expanded_doc, score))
            sentence_results = expanded

        # 合并标准 + 句子结果（按内容去重）
        final = self._merge_standard_and_sentence(
            standard_merged, sentence_results, top_k
        )

        # ===== 重排序（对齐阿里云百炼 + RAGFlow）=====
        # 在 RRF 融合后、权限过滤前，用 reranker 对候选结果二次排序
        # 可显著提升 top-k 的精确度（预期提升 10-20%）
        if self._rerank_enabled and final:
            final = self._rerank(query, final)

        # ===== 权限过滤（二次过滤） =====
        before_count = len(final)
        final = self._filter_by_permission(
            final, tenant_id, user_id, user_access_levels
        )
        after_count = len(final)

        # 记录被过滤的数量
        if before_count > after_count:
            for doc, _ in final:
                doc.metadata["access_filtered"] = before_count - after_count

        # 版本冲突处理
        final = self._resolve_version_conflicts(final, top_k)

        # 检索耗时与命中埋点 —— Grafana「RAG Search Latency」面板依赖
        # rag_search_duration_seconds_bucket；指标失败绝不影响检索主流程
        try:
            from src.api.metrics import record_rag_search

            record_rag_search(
                time.perf_counter() - _rag_t0,
                backend=self.backend,
                hit=bool(final),
            )
        except Exception:  # pragma: no cover - 指标不应影响业务
            logger.debug("record_rag_search metric failed", exc_info=True)

        return final

    # ------------------------------------------------------------------
    # 内部检索方法
    # ------------------------------------------------------------------

    def _vector_search(
        self, query: str, top_k: int, filter_by: dict | None
    ) -> list[tuple[Document, float]]:
        """向量检索 — 根据 backend 自动路由

        Chroma:  本地 LangChain Chroma wrapper
        Milvus:  pymilvus 直连 (多租户 + 标量过滤)
        Remote:  HTTP 调用 rag-service
        Auto:    Milvus 优先，不可用时 Chroma 降级

        所有后端返回结果均经过相似度阈值过滤（对齐阿里云百炼）。
        """
        # ---- Remote 模式 ----
        if self._use_remote:
            return self._filter_by_similarity(
                self._remote_vector_search(query, top_k, filter_by)
            )

        # ---- Milvus 模式 ----
        if self._use_milvus:
            return self._filter_by_similarity(
                self._milvus_vector_search(query, top_k, filter_by)
            )

        # ---- Chroma 模式 (默认/降级) ----
        # DB 级租户隔离：非 default 租户在向量查询时直接带 where 过滤，
        # 即便应用层后过滤（_filter_by_permission）出 bug 也不会跨租户串台；
        # default 沿用历史行为（历史文档可能无 tenant_id 元数据，避免误伤）。
        tenant_id = (filter_by or {}).get("tenant_id")
        where = (
            {"tenant_id": tenant_id} if tenant_id and tenant_id != "default" else None
        )
        results = self.vector_store.search_with_scores(query, top_k, where=where)
        if filter_by:
            results = self._apply_filter(results, filter_by)
        return self._filter_by_similarity(results)

    def _milvus_vector_search(
        self, query: str, top_k: int, filter_by: dict | None
    ) -> list[tuple[Document, float]]:
        """通过 Milvus 进行向量检索"""
        tenant_id = filter_by.get("tenant_id", "") if filter_by else ""
        access_levels = filter_by.get("access_levels") if filter_by else None
        filter_expr = filter_by.get("filter_expr") if filter_by else None

        hits = self.milvus_store.search(
            query_text=query,
            top_k=top_k,
            tenant_id=tenant_id,
            access_levels=access_levels,
            filter_expr=filter_expr,
        )

        results = []
        for h in hits:
            doc = Document(
                page_content=h["text"],
                metadata={
                    "doc_id": h["doc_id"],
                    "chunk_index": h["chunk_index"],
                    "access_level": h["access_level"],
                    "source": h["metadata"].get("source", h["doc_id"]),
                    **h["metadata"],
                },
            )
            results.append((doc, h["score"]))

        return results

    def _remote_vector_search(
        self, query: str, top_k: int, filter_by: dict | None
    ) -> list[tuple[Document, float]]:
        """通过 HTTP 调用远端 RAG Service"""
        import json
        import urllib.error
        import urllib.request

        payload = {
            "query": query,
            "top_k": top_k,
            "tenant_id": filter_by.get("tenant_id", "") if filter_by else "",
            "access_levels": filter_by.get("access_levels") if filter_by else None,
            "filter_expr": filter_by.get("filter_expr") if filter_by else None,
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(  # noqa: S310  URL 来自受信任配置
                f"{self.rag_service_url}/search",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(  # noqa: S310
                req, timeout=settings.rag_service_timeout
            ) as resp:  # nosec B310  # URL 来自受信任配置(settings.rag_service_url)
                body = json.loads(resp.read().decode("utf-8"))

            results = []
            for item in body.get("results", []):
                doc = Document(
                    page_content=item["text"],
                    metadata={
                        "doc_id": item["doc_id"],
                        "chunk_index": item.get("chunk_index", 0),
                        "access_level": item.get("access_level", "public"),
                        "source": item["metadata"].get("source", item["doc_id"]),
                        **item.get("metadata", {}),
                    },
                )
                results.append((doc, item["score"]))

            logger.debug(
                "Remote RAG search: %d hits in %.1fms",
                len(results),
                body.get("latency_ms", 0),
            )
            return results

        except urllib.error.URLError as e:
            logger.error(
                "Remote RAG service unreachable (%s): %s", self.rag_service_url, e
            )
            return []
        except Exception as e:
            logger.exception("Remote RAG search failed: %s", e)
            return []

    def _bm25_search(
        self, query: str, top_k: int, filter_by: dict | None
    ) -> list[tuple[Document, float]]:
        if not self.bm25_retriever:
            return []
        bm25_docs = self.bm25_retriever.invoke(query)[:top_k]
        results = [(doc, 1.0 - i * 0.05) for i, doc in enumerate(bm25_docs)]
        if filter_by:
            results = self._apply_filter(results, filter_by)
        return results

    def _sentence_vector_search(
        self, query: str, top_k: int, filter_by: dict | None
    ) -> list[tuple[Document, float]]:
        results = self.sentence_store.search_with_scores(query, top_k * 2)
        if filter_by:
            results = self._apply_filter(results, filter_by)
        return self._filter_by_similarity(results)

    def _apply_filter(
        self,
        results: list[tuple[Document, float]],
        filter_by: dict,
    ) -> list[tuple[Document, float]]:
        """按元数据过滤结果"""
        filtered = []
        for doc, score in results:
            match = True
            for key, value in filter_by.items():
                if doc.metadata.get(key) != value:
                    match = False
                    break
            if match:
                filtered.append((doc, score))
        return filtered

    def _filter_by_similarity(
        self,
        results: list[tuple[Document, float]],
    ) -> list[tuple[Document, float]]:
        """相似度阈值过滤（对齐阿里云百炼 AI 助理）

        仅保留语义相似度 >= kb_similarity_threshold 的结果。
        阈值范围 0.01~1，默认 0.2。设为 0 则不过滤。
        注意：score 来自各后端的相似度分数（0-1，越大越相似）：
            - Chroma: similarity_search_with_relevance_scores
            - Milvus: 内积/cosine 相似度
            - Remote: 上游 RAG Service 返回的相似度
        """
        if not results:
            return results
        # Phase5 P0-4：把向量通道的「未归一化绝对相似度」盖到 metadata，
        # 供 call_policy.judge_probe 作 smart 模式的绝对判据信号。
        # RRF 的 metadata["score"] 是组内相对分（top1 恒为 1.0），不能承担该判据。
        # 各后端每次检索都新建 Document 对象，盖戳不会污染长期持有的索引文档。
        for doc, score in results:
            try:
                doc.metadata["vector_similarity"] = round(float(score), 6)
            except (TypeError, ValueError):  # noqa: PERF203 - 跳过坏分数继续盖戳
                continue
        threshold = settings.kb_similarity_threshold
        if threshold <= 0:
            return results
        filtered = [(doc, score) for doc, score in results if score >= threshold]
        if len(filtered) < len(results):
            logger.debug(
                "Similarity filter: %d → %d (threshold=%.2f)",
                len(results),
                len(filtered),
                threshold,
            )
        return filtered

    # ------------------------------------------------------------------
    # 融合逻辑
    # ------------------------------------------------------------------

    def _rrf_fusion(
        self,
        vector_results: list[tuple[Document, float]],
        bm25_results: list[tuple[Document, float]],
        top_k: int,
        k: int = 60,
    ) -> list[tuple[Document, float]]:
        """Reciprocal Rank Fusion — 合并两组检索结果

        排序主键是裸 RRF 累积分 1/(k+rank+1)。同一文档在两个通道
        （向量 + BM25）都命中时分数自然累积，多通道共识是最健康的
        相关性信号，必须保持不被权重稀释。

        权重体系（两级相乘，kb_weights × doc_weights，范围 0.5~2，默认 1.0）
        只在裸 RRF 分完全相同时做平局裁决，权重高者优先。

        历史教训（2026-10-06，生产 F02 查询回归）：权重曾直接乘进 RRF 分。
        RRF 相邻 rank 的分差极窄（rank0=1/61 与 rank5=1/66 仅差 8%），
        1.5x 权重等价于把文档提前约 20 个 rank 位，导致高权重文档的 5 个
        低相关 chunk 集体反超他源 rank0 的最相关块，正确资料在截断前出局。
        """
        scores = {}
        weights = {}
        doc_map = {}

        for rank, (doc, _) in enumerate(vector_results):
            doc_id = doc.page_content[:100]
            weight = self._get_kb_weight(doc) * self._get_doc_weight(doc)
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
            weights[doc_id] = weight
            doc_map[doc_id] = doc

        for rank, (doc, _) in enumerate(bm25_results):
            doc_id = doc.page_content[:100]
            weight = self._get_kb_weight(doc) * self._get_doc_weight(doc)
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
            weights[doc_id] = weight
            # 同内容已在向量通道命中时保留向量对象：它是每次检索新建的、
            # metadata 带 vector_similarity 绝对分；BM25 对象是索引期长期持有的
            # 原始文档，覆盖会丢绝对分戳并造成跨查询 metadata 残留。
            if doc_id not in doc_map:
                doc_map[doc_id] = doc

        # 裸 RRF 分优先；仅同分时权重做 tiebreak
        sorted_ids = sorted(
            scores.keys(),
            key=lambda x: (scores[x], weights[x]),
            reverse=True,
        )
        # Phase5 §2.5：留 RRF 原始分到 metadata，供内容级去重时「同键保留高分者」。
        # 该分数区间窄且只由排名决定，不能作「是否检索」判据
        # （判据用 vector_similarity）。
        fused: list[tuple[Document, float]] = []
        for doc_id in sorted_ids[:top_k]:
            doc = doc_map[doc_id]
            raw = scores[doc_id]
            with contextlib.suppress(TypeError, ValueError):
                doc.metadata["raw_score"] = round(float(raw), 6)
            fused.append((doc, raw))
        return fused

    def _get_kb_weight(self, doc: Document) -> float:
        """获取文档所属知识库的权重（对齐阿里云百炼多知识库权重）

        文档 metadata 中的 kb_id 用于匹配权重配置。
        未配置权重的知识库默认权重 1.0。
        """
        if not self._kb_weights_map:
            return 1.0
        kb_id = doc.metadata.get("kb_id", "")
        if not kb_id:
            return 1.0
        return self._kb_weights_map.get(kb_id, 1.0)

    # ------------------------------------------------------------------
    # 重排序（对齐阿里云百炼 + RAGFlow）
    # ------------------------------------------------------------------

    @property
    def reranker(self):
        """懒加载重排序器

        根据 settings.rerank_provider 创建对应的 Reranker 实例：
            - dashscope: 阿里云百炼 gte-rerank（推荐）
            - local_bge: 本地 BGE-reranker
            - llm: LLM 降级方案
        """
        if self._reranker is not None:
            return self._reranker
        if not self._rerank_enabled:
            return None
        try:
            from src.rag.reranker import create_reranker

            self._reranker = create_reranker(
                provider=settings.rerank_provider,
                model_name=settings.rerank_model,
                api_key=settings.openai_api_key,
                api_base=settings.openai_api_base,
            )
            logger.info(
                "Reranker initialized: provider=%s, model=%s",
                settings.rerank_provider,
                settings.rerank_model,
            )
        except Exception as e:
            logger.warning(
                "Reranker init failed (%s: %s), rerank disabled",
                settings.rerank_provider,
                e,
            )
            # 置闩锁而非赋值开关：_rerank_enabled 现在是读时取值的 property，
            # 直接赋值会掩盖配置。闩锁让开关恒为 False，且语义清晰
            # （初始化失败过，本次进程内不再重试）。
            self._rerank_init_failed = True
            self._reranker = None
        return self._reranker

    def _rerank(
        self,
        query: str,
        candidates: list[tuple[Document, float]],
    ) -> list[tuple[Document, float]]:
        """对候选结果重排序

        在 RRF 融合后调用 reranker 对 top 候选二次打分排序。
        失败时降级为原始顺序（不影响主流程）。

        Args:
            query: 查询文本
            candidates: RRF 融合后的候选结果

        Returns:
            重排序后的结果（最多 rerank_top_n 个）
        """
        reranker = self.reranker
        if reranker is None:
            return candidates

        try:
            reranked = reranker.rerank(
                query=query,
                documents=candidates,
                top_n=self._rerank_top_n,
            )
            # 在 metadata 中标记经过重排序
            for doc, score in reranked:
                doc.metadata["reranked"] = True
                doc.metadata["rerank_score"] = score
            return reranked
        except Exception as e:
            logger.warning("Rerank failed, using original order: %s", e)
            return candidates

    def _merge_standard_and_sentence(
        self,
        standard: list[tuple[Document, float]],
        sentence: list[tuple[Document, float]],
        top_k: int,
    ) -> list[tuple[Document, float]]:
        """合并标准粒度 + 句子粒度结果，按内容去重"""
        # 句子通道的 tuple 分数是原始向量相似度（expand_context 可能新建 Document
        # 导致 _filter_by_similarity 的盖戳丢失），这里补盖，供 call_policy 判据使用
        for doc, score in sentence:
            if "vector_similarity" not in doc.metadata:
                with contextlib.suppress(TypeError, ValueError):
                    doc.metadata["vector_similarity"] = round(float(score), 6)
        all_results = standard + sentence
        seen_contents = set()
        merged = []
        for doc, score in all_results:
            # 用前 100 字符做去重 key
            key = doc.page_content[:100]
            if key not in seen_contents:
                seen_contents.add(key)
                merged.append((doc, score))
        return merged[:top_k]

    # ------------------------------------------------------------------
    # 权限过滤
    # ------------------------------------------------------------------

    def _filter_by_permission(
        self,
        results: list[tuple[Document, float]],
        tenant_id: str,
        user_id: str,
        user_access_levels: list[str],
    ) -> list[tuple[Document, float]]:
        """二次权限过滤：租户隔离 + 访问等级过滤

        过滤规则：
            1. 租户隔离：文档的 tenant_id 必须匹配（或未设置则公开）
            2. 权限等级：用户 access_level 必须 >= 文档的 access_level
            3. 用户 ID 标记：记录哪个用户触发了本次检索

        权限等级优先级（从高到低）：
            restricted > confidential > internal > public

        Args:
            results: 检索结果列表
            tenant_id: 当前租户 ID
            user_id: 当前用户 ID
            user_access_levels: 用户拥有的权限等级列表

        Returns:
            过滤后的结果列表
        """
        if not results:
            return results

        # 空 tenant_id 统一归为 "default"，与 add_documents 规则一致
        tenant_id = tenant_id or "default"

        # 权限等级优先级映射
        access_priority = {
            "public": 0,
            "internal": 1,
            "confidential": 2,
            "restricted": 3,
        }

        # 用户最高权限等级
        user_max_level = max(
            (level for level in user_access_levels if level in access_priority),
            key=lambda x: access_priority[x],
            default="public",
        )
        user_priority = access_priority[user_max_level]

        filtered = []
        for doc, score in results:
            meta = doc.metadata

            # 规则 1: 租户隔离
            # 文档若未标注 tenant_id，默认归属 default 租户。
            # 这样既能堵住「漏打 tenant 的文档对所有租户可见」的后门，
            # 又保持 default 租户现状不变（历史文档无 tenant 字段时仍对 default 可见）。
            doc_tenant = meta.get("tenant_id") or "default"
            if doc_tenant != tenant_id:
                # 文档属于其他租户，跳过
                continue

            # 规则 2: 权限等级检查
            doc_access = meta.get("access_level", "public")
            doc_priority = access_priority.get(doc_access, 0)

            if doc_priority > user_priority:
                # 用户权限不足，跳过
                continue

            # 通过所有检查
            filtered.append((doc, score))

        if len(filtered) < len(results):
            logger.info(
                "Permission filter: %d → %d results (tenant=%s, user=%s, access=%s)",
                len(results),
                len(filtered),
                tenant_id,
                user_id,
                user_access_levels,
            )

        return filtered

    def _resolve_version_conflicts(
        self,
        results: list[tuple[Document, float]],
        top_k: int,
    ) -> list[tuple[Document, float]]:
        """解决同一问题召回多个版本的冲突 + 单来源配额截断

        处理顺序（重要，三步不可换位）：
            第 1 步 版本消解：只对「真的有多个版本号」的 source 生效。
                    同一篇文档的多个 chunk 不是版本，必须全部保留。
            第 2 步 来源配额：单个 source 最多贡献 _source_chunk_cap() 条，
                    避免一篇长文档占满 top_k、把其他来源挤出上下文。
            第 3 步 保序截断：保持入参的相关性顺序，最后按 top_k 截断。

        历史缺陷（2026-10-01 修复）：
            原实现把「同一 source 的多个 chunk」当成「同一文档的多个版本」，
            于是 manual.md 的 3 个片段只保留 1 个。判定依据是 _extract_versions
            对无 version 元数据的 chunk 也会生成记录（version_str 为空、
            sort_key=0），len(versions) > 1 就误入版本冲突分支。
            真实场景下这会让长文档的相邻片段（参数表在前、状态码说明在后）
            只进来一条，答案缺关键事实。
        """
        if not results:
            return results

        # ---- 第 1 步：版本消解 ----
        # 只有「同一 source 出现多个不同版本号」才算版本冲突。
        # 判定标准是版本号去重后 > 1，而非 chunk 数 > 1。
        resolved = self._dedupe_versions(results)

        # ---- 第 2 步：来源配额 ----
        cap = self._source_chunk_cap()
        per_source_count: dict[str, int] = {}
        capped: list[tuple[Document, float]] = []
        for doc, score in resolved:
            source = doc.metadata.get("source", "unknown")
            n = per_source_count.get(source, 0)
            if n >= cap:
                continue
            per_source_count[source] = n + 1
            capped.append((doc, score))

        # ---- 第 3 步：保序 + top_k ----
        return capped[:top_k]

    def _dedupe_versions(
        self,
        results: list[tuple[Document, float]],
    ) -> list[tuple[Document, float]]:
        """按 source 消解版本冲突，同时保持全局相关性顺序

        返回顺序与入参一致（仅剔除被判定为「旧版本/废弃版本」的项）。
        无版本号的 chunk 一律保留。
        """
        from collections import defaultdict

        # 按 source 收集，用于判断哪些 source 存在真实版本冲突
        groups: dict[str, list[tuple[Document, float]]] = defaultdict(list)
        for doc, score in results:
            groups[doc.metadata.get("source", "unknown")].append((doc, score))

        # 每个 source：决定哪些 doc 要剔除
        drop_ids: set = set()
        conflict_warnings: list[str] = []

        for source, group_docs in groups.items():
            versions = self._extract_versions(group_docs)
            # 版本号去重后仍 <= 1 → 没有版本冲突，全部保留
            distinct_versions = {v["version"] for v in versions}
            if len(distinct_versions) <= 1:
                continue

            sorted_versions = self._sort_versions(versions)
            active = [
                v
                for v in sorted_versions
                if v["status"] not in ("deprecated", "superseded", "archived")
            ]

            if not active:
                # 全部废弃：保留最新的废弃版本作参考，其余剔除
                keep = sorted_versions[-1]["doc_tuple"]
                conflict_warnings.append(
                    f"警告：文档 {source} 的所有版本均已废弃，仅供参考"
                )
            else:
                keep = active[-1]["doc_tuple"]
                if len(active) > 1:
                    latest_ver = active[-1].get("version", "latest")
                    other_vers = [
                        v.get("version", f"v{i}") for i, v in enumerate(active[:-1])
                    ]
                    conflict_warnings.append(
                        f"冲突：文档 {source} 有多个活跃版本 "
                        f"({', '.join(other_vers)})，已选择最新版本 {latest_ver}。"
                        f"请确认是否需要切换到其他版本。"
                    )

            for doc, _score in group_docs:
                if doc is not keep[0]:
                    drop_ids.add(id(doc))

        kept = [(d, s) for d, s in results if id(d) not in drop_ids]

        if conflict_warnings and kept:
            kept[0][0].metadata["version_conflicts"] = conflict_warnings
            kept[0][0].metadata["has_conflicts"] = True
            logger.warning("Version conflicts detected: %s", conflict_warnings)

        return kept

    def _extract_versions(self, docs: list[tuple[Document, float]]) -> list[dict]:
        """从文档元数据中提取版本号信息

        Returns:
            [{"version": "v3.2", "sort_key": 302,
              "status": "active", "doc_tuple": ...}, ...]
        """
        versions = []
        for doc, score in docs:
            meta = doc.metadata

            # 尝试从 metadata 中提取版本号
            version_str = meta.get("version", "")
            if not version_str:
                # 尝试从 source 文件名中提取
                source = meta.get("source", "")
                match = re.search(r"v(\d+)\.?(\d*)", source)
                if match:
                    version_str = f"v{match.group(1)}.{match.group(2) or '0'}"

            # 解析版本号
            sort_key = self._version_to_sort_key(version_str)

            # 获取状态
            status = meta.get("status", "active")
            if status == "superseded":
                status = "deprecated"

            versions.append(
                {
                    "version": version_str or "unknown",
                    "sort_key": sort_key,
                    "status": status,
                    "doc_tuple": (doc, score),
                }
            )

        return versions

    def _version_to_sort_key(self, version_str: str) -> int:
        """将版本号字符串转换为可排序的整数

        "v3.2" → 302
        "v1.0" → 100
        "unknown" → 0
        """
        if not version_str or version_str == "unknown":
            return 0

        match = re.search(r"v?(\d+)\.?(\d*)", version_str)
        if match:
            major = int(match.group(1))
            minor = int(match.group(2) or "0")
            return major * 100 + minor
        return 0

    def _sort_versions(self, versions: list[dict]) -> list[dict]:
        """按版本号升序排序"""
        return sorted(versions, key=lambda v: v["sort_key"])

    def _get_latest_active_version(self, versions: list[dict]) -> dict | None:
        """获取最新的活跃版本"""
        active = [
            v
            for v in versions
            if v["status"] not in ("deprecated", "superseded", "archived")
        ]
        if active:
            return max(active, key=lambda v: v["sort_key"])
        return None

    def delete_collection(self) -> None:
        """清理向量库"""
        self.vector_store.delete_collection()
        self.bm25_retriever = None
        self._all_documents = []

        if self.sentence_store:
            self.sentence_store.delete_collection()
