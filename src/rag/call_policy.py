"""kb_call_mode 检索判据：smart 模式的规则短路 + 探测式判定（Phase5 语义收口）。

设计约束（对齐 Phase5 拆解方案 §2.2 / §2.5 / §5）：
    1. 纯函数模块：不导入 settings、不读环境变量、不调用 LLM / 网络，
       所有阈值由调用方（rag_node）显式传入，便于单测与热更新口径对齐。
    2. 判据异常一律回落「执行检索」（宁可多检不漏检），由 ``decide_retrieval``
       内建兜底，调用方无需再包 try。
    3. 探测即正式检索的第一次调用：``judge_probe`` 只消费已有探测结果，
       自身不发起任何检索；判定命中时由调用方直接复用该结果（不重复检索）。

分数口径说明（决定判据为何这样写，勿删）：
    当前 ``HybridRetriever.search()`` 返回的分数都是「集合内相对分」：
      - ``metadata["score"]`` = RRF 原始分 / 组内最高分（``retriever.py:320-334``），
        归一化口径保证 top1 恒为 1.0；
      - ``metadata["rerank_score"]`` 由 ``BaseReranker._normalize`` 处理
        （``reranker.py:91-111``）：local_bge 输出为 logits（不在 [0, 1]）→ min-max
        归一化 → top1 同样恒为 1.0。
    结论：**相对分不能作为「是否检索」的判据**——任何非负阈值都会恒命中，
    smart 会退化成 always。RRF 原始分（``raw_score``）同样不可靠：它由排名决定
    （权值 /(k+rank+1)），单榜下限 1/61≈0.0164、双榜上限 2/61≈0.0328，区间窄
    且与语义相关性无单调关系。因此本模块按优先级选择判据信号，并把
    「无绝对信号」时的退化行为显式标注出来：

      a) ``metadata["vector_similarity"]``（未归一化的向量相似度，绝对语义）
         → 用它，门槛即 ``kb_similarity_threshold``；
      b) 调用方显式给出 ``min_raw_score`` → 用 RRF 原始分下限（需生产实测标定）；
      c) 两者皆无 → 退化为「探测列表非空即命中」（``signal="nonempty"``，保守）。

    即：想要 smart 具备真正的判别力，需由检索侧补出方案 a) 的绝对信号；
    在信号补齐前，本模块的默认行为（c）保证「宁多检不漏检」，不会误杀。
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# kb_call_mode 取值与回落（Phase5 决策 2 / 3：默认 always，非法值回落 always）
# ----------------------------------------------------------------------
MODE_ALWAYS = "always"
MODE_SMART = "smart"
MODE_NEVER = "never"
VALID_MODES: tuple[str, ...] = (MODE_ALWAYS, MODE_SMART, MODE_NEVER)

#: 同一 query 的检索次数软上限（含预检索/探测，Phase5 §2.5）
SOFT_RETRIEVAL_LIMIT = 3

# 判据原因码（写入日志与回答元数据 retrieval_decided_by）
REASON_RULE = "rule"
REASON_SCORE = "score"
REASON_SCORE_REJECT = "score_reject"
REASON_FALLBACK = "fallback"


def resolve_mode(raw: Any, *, default: str = MODE_ALWAYS) -> tuple[str, bool]:
    """归一化 kb_call_mode，返回 ``(生效模式, 是否发生回落)``。

    非法值（含拼写错误/大小写混杂/前后空白）统一回落到 ``default``。
    Phase5 决策 3：``default`` 为 ``always``——与生产默认值对齐，行为最可预测。
    未配置（None / 空串）视为「采用默认值」，不算回落（``fallback_used=False``）。
    """
    if raw is None:
        return default, False
    text = str(raw).strip().lower()
    if not text:
        return default, False
    if text in VALID_MODES:
        return text, False
    logger.warning("未知 kb_call_mode=%r，回落 %s", raw, default)
    return default, True


# ----------------------------------------------------------------------
# 文本归一化与内容级去重（Phase5 §2.5：缺口 4 收口）
# ----------------------------------------------------------------------
_WS_RE = re.compile(r"\s+")


def normalize_text(text: Any) -> str:
    """内容归一化：NFKC 统一全角/半角 → 折叠连续空白 → 去首尾空白。

    NFKC 覆盖工业文档常见的全角型号/参数写法（``Ｅ－２０７１`` → ``E-2071``），
    同时不影响中文正文。注意 NFKC 的连带效果：``８５℃`` → ``85°C``（℃ 被分解为
    度符号 + C）。这里只要求「同一内容归一化结果稳定一致」，不要求保留原始字符。
    """
    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text))
    return _WS_RE.sub(" ", value).strip()


def content_key(text: Any) -> str:
    """内容级去重主键：``sha1(normalize_text(text))``。"""
    payload = normalize_text(text).encode("utf-8")
    # sha1 仅用作内容指纹（去重），不承担任何安全职责
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()  # noqa: S324


def _meta_of(doc: Any) -> dict:
    meta = getattr(doc, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _score_of(doc: Any, field: str) -> float | None:
    """读取 ``metadata[field]`` 并转 float；缺失/非法一律返回 None（不抛错）。"""
    value = _meta_of(doc).get(field)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def doc_dedup_keys(doc: Any) -> tuple[str, str | None]:
    """返回 ``(内容主键, 辅键)``。

    主键：``sha1(normalize_text(page_content))``——内容级，不做 [:100] 截断
    （截断式会把「前 100 字符相同、后续不同」的切片误判为重复）。
    辅键：``doc_id|page``（doc_id 缺失时退用 source），便于同一文档同一页的重复
    切片收敛；两者任一命中即视为重复。
    """
    ck = content_key(getattr(doc, "page_content", ""))
    meta = _meta_of(doc)
    doc_id = meta.get("doc_id") or meta.get("source") or ""
    page = meta.get("page")
    if not doc_id or page is None or page == "":
        return ck, None
    return ck, f"{doc_id}|{page}"


def dedup_docs(docs: Iterable[Any]) -> list:
    """内容级去重，保持首次出现顺序，同键保留分数更高者。

    分数口径：``metadata["raw_score"]`` → ``metadata["score"]`` → 0.0。
    """
    out: list = []
    index: dict[str, int] = {}
    for doc in docs or []:
        ck, aux = doc_dedup_keys(doc)
        keys = [ck] + ([aux] if aux else [])
        existing = next((index[k] for k in keys if k in index), None)
        if existing is None:
            for k in keys:
                index[k] = len(out)
            out.append(doc)
            continue
        new_score = _score_of(doc, "raw_score")
        if new_score is None:
            new_score = _score_of(doc, "score") or 0.0
        old_score = _score_of(out[existing], "raw_score")
        if old_score is None:
            old_score = _score_of(out[existing], "score") or 0.0
        if new_score > old_score:
            out[existing] = doc
    return out


def warn_if_over_budget(
    retrieval_count: int,
    *,
    query: str = "",
    source: str = "",
    limit: int = SOFT_RETRIEVAL_LIMIT,
) -> bool:
    """检索次数软上限观测：超限打 warning 但不阻断（Phase5 §2.5）。

    返回是否超限。硬截断需工具层具备 per-query 计数能力，不在本次范围。
    """
    if retrieval_count > limit:
        logger.warning(
            "检索次数超软上限：count=%d limit=%d source=%s query=%s",
            retrieval_count,
            limit,
            source or "-",
            (query or "")[:60],
        )
        return True
    return False


# ----------------------------------------------------------------------
# A 段：规则前置短路（零外呼、零模型依赖）
# ----------------------------------------------------------------------
_RULE_CHITCHAT = "chitchat"
_RULE_OPERATION = "operation"
_RULE_FOLLOWUP = "followup"

_CHITCHAT_WORDS = (
    "你好",
    "您好",
    "哈喽",
    "哈啰",
    "在吗",
    "在么",
    "谢谢",
    "多谢",
    "感谢",
    "辛苦了",
    "再见",
    "拜拜",
    "早上好",
    "晚上好",
    "下午好",
    "先这样吧",
    "先这样",
    "就这样吧",
    "好的",
    "收到",
    "行吧",
    "嗯嗯",
    "哦哦",
    "嗯",
    "哦",
    "噢",
    "呵呵",
    "hi",
    "hello",
    "hey",
    "bye",
    "thanks",
    "thank you",
)

_OPERATION_WORDS = (
    "转人工",
    "人工客服",
    "找人工",
    "转接人工",
    "要人工",
    "投诉",
    "工单",
    "报修",
    "开票",
    "发票",
)

_FOLLOWUP_WORDS = (
    "继续说",
    "接着讲",
    "接着上面",
    "展开说",
    "详细说",
    "说下去",
    "然后呢",
    "上面那",
    "刚才那",
    "回到刚才",
    "还有呢",
)

# 技术/业务特征：命中即**不**允许规则短路（防误杀「你好，E-2071 怎么处理」这类混流提问）
_TECHNICAL_HINT_RE = re.compile(
    r"[0-9a-z]|怎么|如何|为什么|为何|多少|多久|几天|什么|哪里|哪个|哪些|怎样|"
    r"能否|是否|流程|步骤|参数|设置|配置|故障|报错|报警|错误码|代码|型号|规格|"
    r"原因|处理|解决|原理|区别|政策|标准|要求",
    re.IGNORECASE,
)

_PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)


@dataclass(frozen=True)
class RuleVerdict:
    """A 段判定结果：``matched=True`` 表示短路（不检索）。"""

    matched: bool
    rule: str | None = None


def _has_technical_hint(text: str) -> bool:
    return bool(_TECHNICAL_HINT_RE.search(text))


def apply_rules(question: Any, *, has_prior_citations: bool = False) -> RuleVerdict:
    """A 段规则短路。命中表示「无需检索」，由调用方直接跳过检索。

    三类规则（均先过技术特征闸门，宁可漏放不误放）：
      - ``chitchat``：寒暄/致谢/告别，去掉寒暄词与标点后无实质内容；
      - ``operation``：转人工/工单/投诉等纯操作指令；
      - ``followup``：纯指代承接短句，且上一轮已有可信引用。
    """
    text = normalize_text(question).lower()
    if not text:
        return RuleVerdict(False)

    # 先剥离寒暄词与标点，再对「残余实质内容」做技术特征闸门：
    #   残余为空/单字 → 纯寒暄；残余含型号(字母数字)/疑问词/业务词 → 放行检索。
    # 若先对整句做闸门，"Hello"/"hi" 会被 [a-z] 误伤。
    stripped = _PUNCT_RE.sub("", text)
    for word in _CHITCHAT_WORDS:
        stripped = stripped.replace(word, "")
    if _has_technical_hint(stripped):
        return RuleVerdict(False)
    if len(stripped) <= 1:
        return RuleVerdict(True, _RULE_CHITCHAT)

    if any(word in text for word in _OPERATION_WORDS):
        return RuleVerdict(True, _RULE_OPERATION)

    if (
        has_prior_citations
        and len(text) <= 12
        and any(word in text for word in _FOLLOWUP_WORDS)
    ):
        return RuleVerdict(True, _RULE_FOLLOWUP)

    return RuleVerdict(False)


# ----------------------------------------------------------------------
# C 段：探测式判定（探测即正式检索，不重复调用）
# ----------------------------------------------------------------------
SIGNAL_EMPTY = "empty"
SIGNAL_VECTOR_SIMILARITY = "vector_similarity"
SIGNAL_RAW_RRF = "raw_rrf"
SIGNAL_NONEMPTY = "nonempty"


@dataclass(frozen=True)
class ProbeVerdict:
    """C 段判定结果（只读消费探测结果，不发起检索）。"""

    should_inject: bool
    signal: str
    hit_count: int
    doc_count: int
    top1_raw_score: float | None = None
    top1_rel_score: float | None = None


def judge_probe(
    docs: Sequence[Any] | None,
    *,
    min_raw_score: float | None = None,
    min_vector_similarity: float | None = None,
) -> ProbeVerdict:
    """对探测（= 第一次正式检索）结果做判定。

    信号优先级：空列表 → 未归一化向量相似度 → RRF 原始分下限 → 非空即命中。
    ``min_vector_similarity`` / ``min_raw_score`` 为 ``None`` 表示该信号不可用，
    不参与判定（避免用未标定的阈值静默误杀）。
    """
    items = list(docs or [])
    if not items:
        return ProbeVerdict(False, SIGNAL_EMPTY, 0, 0)

    top1_rel = _score_of(items[0], "score")
    top1_raw = _score_of(items[0], "raw_score")

    if min_vector_similarity is not None:
        sims = [_score_of(d, "vector_similarity") for d in items]
        if any(s is not None for s in sims):
            hits = sum(1 for s in sims if s is not None and s >= min_vector_similarity)
            return ProbeVerdict(
                hits >= 1,
                SIGNAL_VECTOR_SIMILARITY,
                hits,
                len(items),
                top1_raw,
                top1_rel,
            )

    if min_raw_score is not None:
        raws = [_score_of(d, "raw_score") for d in items]
        if any(r is not None for r in raws):
            hits = sum(1 for r in raws if r is not None and r >= min_raw_score)
            return ProbeVerdict(
                hits >= 1, SIGNAL_RAW_RRF, hits, len(items), top1_raw, top1_rel
            )

    # 无绝对信号：保守退化为「非空即命中」（宁多检不漏检，见模块 docstring）
    return ProbeVerdict(
        True, SIGNAL_NONEMPTY, len(items), len(items), top1_raw, top1_rel
    )


# ----------------------------------------------------------------------
# 聚合入口
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class PolicyDecision:
    """smart 模式检索决策。

    - ``should_retrieve``：是否（复用探测结果/发起检索）；
    - ``reason``：``rule`` / ``score`` / ``score_reject`` / ``fallback``；
    - ``probe_reused``：探测结果是否可直接复用为正式检索结果（永远不重复检索）；
    - ``needs_probe``：A 段未命中且未提供探测结果，调用方需先探测后二次调用。
    """

    should_retrieve: bool
    reason: str
    rule: str | None = None
    signal: str | None = None
    probe_reused: bool = False
    needs_probe: bool = False
    hit_count: int = 0
    doc_count: int = 0
    top1_score: float | None = None


def decide_retrieval(
    question: Any,
    *,
    probe_docs: Sequence[Any] | None = None,
    has_prior_citations: bool = False,
    min_raw_score: float | None = None,
    min_vector_similarity: float | None = None,
) -> PolicyDecision:
    """smart 模式两段式决策：A 段规则短路 → C 段探测判定。

    调用约定（消除「一次 query 两次检索」）：
      1. 首次调用（``probe_docs=None``）：命中 A 段 → 直接不检索（0 次检索）；
         未命中 → 返回 ``needs_probe=True``，调用方执行**唯一一次**检索；
      2. 二次调用（带上刚拿到的 ``probe_docs``）：判定命中 → ``probe_reused=True``，
         该结果即正式检索结果；判定未命中 → 不注入（结果弃用，不额外检索）。

    判据内部异常一律回落 ``should_retrieve=True``（reason=``fallback``）。
    """
    try:
        verdict = apply_rules(question, has_prior_citations=has_prior_citations)
        if verdict.matched:
            return PolicyDecision(False, REASON_RULE, rule=verdict.rule)

        if probe_docs is None:
            return PolicyDecision(
                True, REASON_FALLBACK, signal="missing_probe", needs_probe=True
            )

        probe = judge_probe(
            probe_docs,
            min_raw_score=min_raw_score,
            min_vector_similarity=min_vector_similarity,
        )
        return PolicyDecision(
            probe.should_inject,
            REASON_SCORE if probe.should_inject else REASON_SCORE_REJECT,
            signal=probe.signal,
            probe_reused=probe.should_inject,
            hit_count=probe.hit_count,
            doc_count=probe.doc_count,
            top1_score=probe.top1_rel_score,
        )
    except Exception:  # noqa: BLE001 - 判据异常必须回落检索而非中断问答
        logger.warning("kb_call_mode 判据异常，回落为执行检索", exc_info=True)
        return PolicyDecision(True, REASON_FALLBACK, signal="policy_error")
