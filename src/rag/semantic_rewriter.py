"""LLM 驱动的语义查询改写（HyDE / 多查询扩展）。

与 query_rewriter.py 的本质区别：
    - query_rewriter 是纯正则同义词表，零 LLM 开销，生产默认开启
    - 本模块每次调用都产生一次额外 LLM 生成，CPU 7B 上单跳延迟敏感，
      由 settings.semantic_rewrite_enabled 独立控制，默认关闭

设计纪律（对应项目金标教训）：
    1. 任何异常都降级为空扩展，检索主链路永不因改写器故障受损
    2. HyDE 段落只用于向量嵌入召回，禁止进入生成上下文，模型自身
       不知道这段文字的存在，杜绝假设内容污染最终答案
    3. 提示词只做行为约束，不含具体型号/参数 few-shot，防止 7B 照抄
    4. 多查询问法数硬上限 3，控制 CPU 场景的嵌入调用次数
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SemanticExpansion:
    """一次语义改写的产物。

    extra_queries: 多查询问法（不含原始 query），喂向量/BM25 补召回
    hyde_text: 假设答案段落，仅喂向量通道
    两个字段皆空表示改写未生效，调用方回退普通检索。
    """

    extra_queries: list[str] = field(default_factory=list)
    hyde_text: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.extra_queries and not self.hyde_text


_HYDE_PROMPT_TEMPLATE = (
    "你是工业测温设备手册专家。用户提问：{query}\n\n"
    "请写一段可能出现在官方手册答案中的概括性段落，用于资料检索，"
    "要求：\n"
    "1. 用中文，80 字以内，只写与检索相关的术语和概念\n"
    "2. 禁止编造具体数值、型号、故障码；不确定的参数用概括表述\n"
    "3. 直接输出段落本身，不要任何前缀、序号或解释"
)

_MULTI_QUERY_PROMPT_TEMPLATE = (
    "你是检索查询改写助手。把下面的用户提问改写成 {n} 个语义等价、"
    "用词不同的中文问法，用于召回同一批手册资料。\n"
    "用户提问：{query}\n\n"
    "要求：每行一个问法，用 1. 2. 3. 编号；保持原意，不新增信息，"
    "不输出编号以外的任何内容。"
)


def _make_llm():
    # 延迟导入避免模块加载期拉起模型工厂依赖
    from src.agent.cancellable_llm import make_chat_model

    return make_chat_model(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        temperature=0.0,
        max_tokens=settings.semantic_rewrite_max_tokens,
    )


def _strip_numbered_lines(text: str) -> list[str]:
    """解析「1. xxx 2. xxx」编号输出，容忍顿号、括号等编号变体。"""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^\d+\s*[\.、\)）]\s*", "", line).strip()
        if line:
            lines.append(line)
    return lines


def generate_hyde_document(query: str) -> str:
    """生成假设答案段落。失败或空输出返回空串。"""
    try:
        llm = _make_llm()
        result = llm.invoke(_HYDE_PROMPT_TEMPLATE.format(query=query))
        text = (getattr(result, "content", "") or "").strip()
        # 模型偶尔加前缀解释，按首句截断保护，保留检索语义主体
        return text[:300]
    except Exception as e:  # noqa: BLE001 - 改写是增强能力，失败必须静默降级
        logger.warning("HyDE generation failed, fallback to plain search: %s", e)
        return ""


def generate_alternative_queries(query: str, n: int) -> list[str]:
    """生成 N 个同义问法。解析失败、重复、与原句相同的条目全部剔除。"""
    n = max(1, min(3, int(n)))
    try:
        llm = _make_llm()
        result = llm.invoke(_MULTI_QUERY_PROMPT_TEMPLATE.format(query=query, n=n))
        raw = getattr(result, "content", "") or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("Multi-query generation failed, fallback to plain search: %s", e)
        return []

    seen = {query.strip()}
    alternatives: list[str] = []
    for line in _strip_numbered_lines(raw):
        if line in seen:
            continue
        seen.add(line)
        alternatives.append(line)
        if len(alternatives) >= n:
            break
    return alternatives


def build_semantic_expansion(query: str) -> SemanticExpansion:
    """按 settings.semantic_rewrite_mode 组装改写产物的统一入口。

    开关关闭或入参为空时直接返回空扩展，调用方零分支成本。
    """
    if not getattr(settings, "semantic_rewrite_enabled", False) or not query.strip():
        return SemanticExpansion()

    mode = getattr(settings, "semantic_rewrite_mode", "hyde")
    expansion = SemanticExpansion()

    if mode in ("hyde", "both"):
        expansion.hyde_text = generate_hyde_document(query)
    if mode in ("multi_query", "both"):
        expansion.extra_queries = generate_alternative_queries(
            query, getattr(settings, "semantic_rewrite_variants", 2)
        )

    if expansion.is_empty:
        logger.info("Semantic rewrite produced nothing, use plain retrieval")
    return expansion
