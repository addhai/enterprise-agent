"""三级递进式去重处理器

去重策略（按顺序执行）：
    Level 1 精确去重：normalize_text → SHA-256 → 完全相同的文档直接过滤
    Level 2 SimHash 近重去重：SimHash(64-bit) → Hamming distance → 相似度 >95% 过滤
    Level 3 语义去重：预留接口，默认关闭

设计考量：
    - 一级快（O(n)），二级准（O(n²) 但 n 小），三级预留
    - SimHash 用纯 Python + numpy 实现，不依赖分词器
    - 每级去重后文档数递减，二级只对一级剩余文档做
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from src.config import settings
from src.rag.processors.base import BaseBatchProcessor, ProcessingContext

if TYPE_CHECKING:
    from langchain_core.documents import Document as _Doc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 文本规范化（去重用）
# ---------------------------------------------------------------------------


def _normalize_for_hash(text: str) -> str:
    """为哈希计算做轻量规范化

    全角→半角、合并空白、统一换行。
    不做语义变更，只做格式标准化。
    """
    if not text:
        return text
    result = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        else:
            result.append(ch)
    text = "".join(result)
    text = text.replace("……", "…")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


# ---------------------------------------------------------------------------
# Level 1: 精确去重
# ---------------------------------------------------------------------------


def _exact_dedup(docs: List["_Doc"], window: int) -> Tuple[List["_Doc"], int]:
    """精确去重：整文档内容 SHA-256 完全匹配

    Args:
        docs: 待去重的文档列表
        window: 用于计算哈希的文本窗口长度

    Returns:
        (去重后的文档列表, 移除的文档数)
    """
    seen: Dict[str, "_Doc"] = {}
    duplicates = 0

    for doc in docs:
        normalized = _normalize_for_hash(doc.page_content)[:window]
        h = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if h not in seen:
            seen[h] = doc
        else:
            existing = seen[h]
            # 保留 metadata 更全的文档
            if len(doc.metadata) > len(existing.metadata):
                seen[h] = doc
            duplicates += 1

    result = list(seen.values())
    if duplicates > 0:
        logger.info("Exact dedup: removed %d duplicates", duplicates)
    return result, duplicates


# ---------------------------------------------------------------------------
# Level 2: SimHash 近重去重
# ---------------------------------------------------------------------------


def _char_ngrams(text: str, n: int = 3) -> List[str]:
    """字符级 n-gram 分词

    不依赖外部分词器，中英文通用。
    对小幅修改/格式转换敏感。
    """
    if not text:
        return []
    return [text[i:i + n] for i in range(len(text) - n + 1)]


def _simhash_fingerprint(text: str, fingerprint_bits: int = 64, ngram_size: int = 3) -> int:
    """计算文本的 SimHash 指纹

    算法：
        1. 字符级 n-gram 分词
        2. 对每个 token 计算 SHA-1 哈希
        3. 将哈希值映射为 fingerprint_bits 维向量（哈希值第 i 位为 1 → 权重 +1，否则 -1）
        4. 累加所有 token 的加权向量
        5. 按符号位得到最终指纹

    Args:
        text: 输入文本
        fingerprint_bits: 指纹位数（64 或 128）
        ngram_size: n-gram 大小

    Returns:
        64-bit 整数表示的指纹
    """
    # 分词
    tokens = _char_ngrams(_normalize_for_hash(text), ngram_size)
    if not tokens:
        return 0

    # 初始化权重向量
    weights = [0] * fingerprint_bits

    for token in tokens:
        # 对每个 token 计算 SHA-1 哈希
        h = hashlib.sha1(token.encode("utf-8")).digest()
        # 将哈希值映射为 fingerprint_bits 维向量
        h_int = int.from_bytes(h, byteorder="big")
        for i in range(fingerprint_bits):
            bit = (h_int >> i) & 1
            weights[i] += 1 if bit else -1

    # 按符号位得到最终指纹
    fingerprint = 0
    for i in range(fingerprint_bits):
        if weights[i] > 0:
            fingerprint |= (1 << i)

    return fingerprint


def _hamming_distance(fp_a: int, fp_b: int, bits: int = 64) -> int:
    """计算两个 SimHash 指纹的汉明距离"""
    xor = fp_a ^ fp_b
    return bin(xor).count("1")


def _simhash_similarity(fp_a: int, fp_b: int, bits: int = 64) -> float:
    """计算两个 SimHash 指纹的相似度"""
    dist = _hamming_distance(fp_a, fp_b, bits)
    return 1.0 - dist / bits


def _simhash_dedup(
    docs: List["_Doc"],
    threshold: float = 0.95,
    window: int = 500,
    fingerprint_bits: int = 64,
) -> Tuple[List["_Doc"], int]:
    """SimHash 近重去重

    对一级去重后的文档做 SimHash 计算，相似度超过阈值的文档视为近重，
    保留 metadata 更全 + 内容更长的文档。

    Args:
        docs: 一级去重后的文档列表
        threshold: 相似度阈值（默认 0.95，即 Hamming distance ≤ 3 for 64-bit）
        window: 用于计算 SimHash 的文本窗口长度
        fingerprint_bits: SimHash 指纹位数

    Returns:
        (去重后的文档列表, 移除的文档数)
    """
    if len(docs) < 2:
        return docs, 0

    # 计算每个文档的 SimHash 指纹
    fingerprints: List[Tuple[int, int]] = []  # (index, fingerprint)
    for i, doc in enumerate(docs):
        text = _normalize_for_hash(doc.page_content)[:window]
        fp = _simhash_fingerprint(text, fingerprint_bits)
        fingerprints.append((i, fp))

    # 两两比较（只比较指纹相近的文档对）
    # 优化：先用第一个 bit 分组，只比较同组的文档对
    # 对于小规模文档集，O(n²) 可接受
    kept: set = set(range(len(docs)))
    duplicates = 0

    for i in range(len(fingerprints)):
        if i not in kept:
            continue
        for j in range(i + 1, len(fingerprints)):
            if j not in kept:
                continue
            _, fp_i = fingerprints[i]
            _, fp_j = fingerprints[j]
            sim = _simhash_similarity(fp_i, fp_j, fingerprint_bits)
            if sim >= threshold:
                # 找到重复文档，保留更好的那个
                doc_i = docs[i]
                doc_j = docs[j]
                # 评分：metadata 数量 + 内容长度
                score_i = len(doc_i.metadata) + len(doc_i.page_content) * 0.1
                score_j = len(doc_j.metadata) + len(doc_j.page_content) * 0.1
                if score_j > score_i:
                    kept.discard(i)
                else:
                    kept.discard(j)
                duplicates += 1

    result = [docs[i] for i in sorted(kept)]

    if duplicates > 0:
        logger.info(
            "SimHash dedup: removed %d near-duplicates (threshold=%.2f, %d docs checked)",
            duplicates, threshold, len(docs),
        )
    return result, duplicates


# ---------------------------------------------------------------------------
# Level 3: 语义去重（预留接口）
# ---------------------------------------------------------------------------


class SemanticDedupProcessor(BaseBatchProcessor):
    """语义去重处理器（预留接口）

    通过轻量 Embedding 计算文档相似度，过滤语义重复的段落。

    当前默认关闭，通过 config 或构造函数参数启用。
    需要嵌入模型支持时才会实际执行。
    """

    def __init__(self, threshold: float = 0.90) -> None:
        self.threshold = threshold

    @property
    def name(self) -> str:
        return "semantic_dedup"

    def process_batch(
        self, docs: List["_Doc"], ctx: ProcessingContext
    ) -> List["_Doc"]:
        logger.info(
            "Semantic dedup is reserved for future implementation. "
            "Skipping %d docs.", len(docs),
        )
        return docs


# ---------------------------------------------------------------------------
# 向后兼容别名
# ---------------------------------------------------------------------------

def _content_hash(text: str, window: int = 200) -> str:
    """向后兼容：精确内容哈希（等价于 Level 1 的精确去重）"""
    normalized = _normalize_for_hash(text)[:window]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# 主处理器：三级去重流水线
# ---------------------------------------------------------------------------


class DeduplicateProcessor(BaseBatchProcessor):
    """三级递进式去重处理器

    执行顺序：
        Level 1: 精确去重（SHA-256，完全匹配）
        Level 2: SimHash 近重去重（相似度阈值过滤）
        Level 3: 语义去重（预留，默认关闭）

    配置优先级：构造函数参数 > settings.py 默认值
    """

    def __init__(
        self,
        window: int = 200,
        simhash_threshold: Optional[float] = None,
        simhash_enabled: Optional[bool] = None,
        semantic_enabled: Optional[bool] = None,
        semantic_threshold: Optional[float] = None,
    ) -> None:
        self.window = window
        self.simhash_threshold = (
            simhash_threshold
            if simhash_threshold is not None
            else settings.dedup_simhash_threshold
        )
        self.simhash_enabled = (
            simhash_enabled
            if simhash_enabled is not None
            else settings.dedup_simhash_enabled
        )
        self.semantic_enabled = (
            semantic_enabled
            if semantic_enabled is not None
            else settings.dedup_semantic_enabled
        )
        self.semantic_threshold = (
            semantic_threshold
            if semantic_threshold is not None
            else settings.dedup_semantic_threshold
        )

    @property
    def name(self) -> str:
        return "deduplicate"

    def process_batch(
        self, docs: List["_Doc"], ctx: ProcessingContext
    ) -> List["_Doc"]:
        """执行三级去重流水线"""
        if not docs:
            return []

        total_before = len(docs)
        total_dropped = 0

        # Level 1: 精确去重
        docs, exact_dropped = _exact_dedup(docs, self.window)
        total_dropped += exact_dropped
        ctx.inc("exact_dropped", exact_dropped)
        logger.info(
            "Dedup Level 1 (exact): %d → %d docs (removed %d)",
            total_before, len(docs), exact_dropped,
        )

        # Level 2: SimHash 近重去重
        if self.simhash_enabled and len(docs) >= 2:
            docs, sim_dropped = _simhash_dedup(
                docs,
                threshold=self.simhash_threshold,
                window=self.window,
            )
            total_dropped += sim_dropped
            ctx.inc("simhash_dropped", sim_dropped)
            logger.info(
                "Dedup Level 2 (simhash): %d → %d docs (removed %d)",
                total_before - exact_dropped, len(docs), sim_dropped,
            )

        # Level 3: 语义去重（预留）
        if self.semantic_enabled:
            semantic_proc = SemanticDedupProcessor(
                threshold=self.semantic_threshold
            )
            docs = semantic_proc.process_batch(docs, ctx)

        ctx.inc("total_dropped", total_dropped)
        ctx.inc("final_count", len(docs))

        logger.info(
            "Dedup complete: %d → %d docs (exact=%d, simhash=%d)",
            total_before, len(docs), exact_dropped,
            total_dropped - exact_dropped,
        )
        return docs
