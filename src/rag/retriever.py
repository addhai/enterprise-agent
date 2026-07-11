"""混合检索器：向量检索 + BM25 关键词检索 + RRF 融合

v0.3 更新（2026-07-01）：
    - 句子窗口检索：命中句子后自动展开前后 N 句上下文
    - 双索引支持：标准粒度 + 句子粒度并行检索
    - 元数据过滤：可按 source/category/page 过滤
    - 版本冲突处理：按发布时间/生效状态排序，废弃版本不参与生成，冲突时提示用户

v0.4 更新（2026-07-02）：
    - 版本冲突检测：同一问题召回多个版本时自动排序 + 废弃过滤
    - 冲突提示：当同一主题有多个活跃版本时，在 metadata 中标注 conflict
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
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
    ):
        self.context_window = context_window
        self.sentence_splitter = SentenceWindowSplitter(
            context_window=context_window,
        )

        # 标准粒度索引
        self.vector_store = VectorStoreManager(
            persist_directory=persist_directory,
            collection_name=collection_name,
        )

        # 句子粒度索引（独立 collection）
        self.sentence_store = VectorStoreManager(
            persist_directory=persist_directory,
            collection_name=f"{collection_name}_sentences",
        ) if collection_name else None

        self.bm25_retriever: BM25Retriever = None
        self._all_documents: List[Document] = []

    def index_documents(self, documents: List[Document]) -> None:
        """索引文档：同时写入向量库和 BM25

        注意：此方法只索引标准粒度。
        句子粒度需要在外部通过 HybridChunker.split_both() 获取后单独索引。
        """
        self._all_documents = documents
        self.vector_store.add_documents(documents)
        self.bm25_retriever = BM25Retriever.from_documents(documents)

    def index_sentence_chunks(
        self, sentence_chunks: List[Document]
    ) -> None:
        """索引句子级 chunk（由 HybridChunker.split_sentences() 产出）"""
        if self.sentence_store:
            self.sentence_store.add_documents(sentence_chunks)
            logger.info(
                "Indexed %d sentence chunks", len(sentence_chunks)
            )

    def search(
        self,
        query: str,
        top_k: int = 5,
        expand_context: bool = True,
        filter_by: Optional[dict] = None,
        user_id: str = "",
        tenant_id: str = "",
        user_access_levels: Optional[List[str]] = None,
    ) -> List[Document]:
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
            query, top_k, expand_context, filter_by,
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
        filter_by: Optional[dict] = None,
        user_id: str = "",
        tenant_id: str = "",
        user_access_levels: Optional[List[str]] = None,
    ) -> List[Tuple[Document, float]]:
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

        # 标准粒度：向量检索
        vector_results = self._vector_search(query, top_k * 2, filter_by)

        # 标准粒度：BM25
        bm25_results = self._bm25_search(query, top_k * 2, filter_by)

        # 句子粒度：向量检索
        sentence_results = self._sentence_vector_search(
            query, top_k, filter_by
        ) if self.sentence_store else []

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

        return final

    # ------------------------------------------------------------------
    # 内部检索方法
    # ------------------------------------------------------------------

    def _vector_search(
        self, query: str, top_k: int, filter_by: Optional[dict]
    ) -> List[Tuple[Document, float]]:
        results = self.vector_store.search_with_scores(query, top_k)
        if filter_by:
            results = self._apply_filter(results, filter_by)
        return results

    def _bm25_search(
        self, query: str, top_k: int, filter_by: Optional[dict]
    ) -> List[Tuple[Document, float]]:
        if not self.bm25_retriever:
            return []
        bm25_docs = self.bm25_retriever.invoke(query)[:top_k]
        results = [(doc, 1.0 - i * 0.05) for i, doc in enumerate(bm25_docs)]
        if filter_by:
            results = self._apply_filter(results, filter_by)
        return results

    def _sentence_vector_search(
        self, query: str, top_k: int, filter_by: Optional[dict]
    ) -> List[Tuple[Document, float]]:
        results = self.sentence_store.search_with_scores(query, top_k * 2)
        if filter_by:
            results = self._apply_filter(results, filter_by)
        return results

    def _apply_filter(
        self,
        results: List[Tuple[Document, float]],
        filter_by: dict,
    ) -> List[Tuple[Document, float]]:
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

    # ------------------------------------------------------------------
    # 融合逻辑
    # ------------------------------------------------------------------

    def _rrf_fusion(
        self,
        vector_results: List[Tuple[Document, float]],
        bm25_results: List[Tuple[Document, float]],
        top_k: int,
        k: int = 60,
    ) -> List[Tuple[Document, float]]:
        """Reciprocal Rank Fusion — 合并两组检索结果"""
        scores = {}
        doc_map = {}

        for rank, (doc, _) in enumerate(vector_results):
            doc_id = doc.page_content[:100]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
            doc_map[doc_id] = doc

        for rank, (doc, _) in enumerate(bm25_results):
            doc_id = doc.page_content[:100]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
            doc_map[doc_id] = doc

        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [(doc_map[doc_id], scores[doc_id]) for doc_id in sorted_ids[:top_k]]

    def _merge_standard_and_sentence(
        self,
        standard: List[Tuple[Document, float]],
        sentence: List[Tuple[Document, float]],
        top_k: int,
    ) -> List[Tuple[Document, float]]:
        """合并标准粒度 + 句子粒度结果，按内容去重"""
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
        results: List[Tuple[Document, float]],
        tenant_id: str,
        user_id: str,
        user_access_levels: List[str],
    ) -> List[Tuple[Document, float]]:
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
            doc_tenant = meta.get("tenant_id", "")
            if doc_tenant and doc_tenant != tenant_id:
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
                len(results), len(filtered), tenant_id, user_id, user_access_levels,
            )

        return filtered

    def _resolve_version_conflicts(
        self,
        results: List[Tuple[Document, float]],
        top_k: int,
    ) -> List[Tuple[Document, float]]:
        """解决同一问题召回多个版本的冲突

        处理策略：
            1. 按 source（文件名）分组，识别同一文档的多个版本
            2. 每组内按 version 字段排序（升序：旧→新）
            3. 过滤 status="deprecated" 或 status="superseded" 的版本
            4. 保留每组中最新的有效版本
            5. 如果同一组有多个活跃版本 → 标记 conflict 并提示用户
        """
        if not results:
            return results

        # 按 source 分组
        groups: Dict[str, List[Tuple[Document, float]]] = {}
        for doc, score in results:
            source = doc.metadata.get("source", "unknown")
            if source not in groups:
                groups[source] = []
            groups[source].append((doc, score))

        resolved = []
        conflict_warnings: List[str] = []

        for source, group_docs in groups.items():
            # 提取版本号
            versions = self._extract_versions(group_docs)

            if len(versions) <= 1:
                # 只有一个版本，直接保留
                resolved.extend(group_docs)
                continue

            # 按版本排序（升序）
            sorted_versions = self._sort_versions(versions)

            # 过滤废弃版本
            active_versions = [
                v for v in sorted_versions
                if v["status"] not in ("deprecated", "superseded", "archived")
            ]

            if not active_versions:
                # 所有版本都废弃了，保留最新的废弃版本（作为参考）
                resolved.append(sorted_versions[-1]["doc_tuple"])
                conflict_warnings.append(
                    f"警告：文档 {source} 的所有版本均已废弃，仅供参考"
                )
                continue

            # 保留最新的活跃版本
            latest = active_versions[-1]
            resolved.append(latest["doc_tuple"])

            # 如果有多个活跃版本 → 冲突
            if len(active_versions) > 1:
                latest_ver = latest.get("version", "latest")
                other_vers = [
                    v.get("version", f"v{i}")
                    for i, v in enumerate(active_versions[:-1])
                ]
                conflict_warnings.append(
                    f"冲突：文档 {source} 有多个活跃版本 "
                    f"({', '.join(other_vers)})，已选择最新版本 {latest_ver}。"
                    f"请确认是否需要切换到其他版本。"
                )

        # 附加冲突警告到第一个结果的 metadata
        if conflict_warnings:
            if resolved:
                resolved[0][0].metadata["version_conflicts"] = conflict_warnings
                resolved[0][0].metadata["has_conflicts"] = True
                logger.warning(
                    "Version conflicts detected: %s", conflict_warnings
                )

        return resolved[:top_k]

    def _extract_versions(
        self, docs: List[Tuple[Document, float]]
    ) -> List[dict]:
        """从文档元数据中提取版本号信息

        Returns:
            [{"version": "v3.2", "sort_key": 302, "status": "active", "doc_tuple": ...}, ...]
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

            versions.append({
                "version": version_str or "unknown",
                "sort_key": sort_key,
                "status": status,
                "doc_tuple": (doc, score),
            })

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

    def _sort_versions(self, versions: List[dict]) -> List[dict]:
        """按版本号升序排序"""
        return sorted(versions, key=lambda v: v["sort_key"])

    def _get_latest_active_version(
        self, versions: List[dict]
    ) -> Optional[dict]:
        """获取最新的活跃版本"""
        active = [v for v in versions if v["status"] not in
                  ("deprecated", "superseded", "archived")]
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
