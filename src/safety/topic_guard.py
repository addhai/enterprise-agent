"""话题级安全护栏（规则硬闸门，零 LLM 调用）。

背景（2026-10-07 金标题库首跑实测）：
    7B 模型在三类边界问题上不可靠，提示词约束（REACT_SYSTEM_PROMPT
    规则 7「无关问题礼貌告知」）会被诱导突破：
      1. 用途禁区（人体医疗测温、火焰内部测温、防爆区）：
         语料 product_spec_manual.md 12.2 有明确「不能」禁令，
         模型仍会输出「37.3℃ 算发烧」「550℃ 以内可以测火焰」。
      2. 越权校准（GR04）：语料 FAQ Q24 / 校准手册附录 A 写明校准模式
         密码保护、普通用户禁止进入，模型仍给出调增益/零点的具体步骤。
      3. 知识库外问题（GR05）：模型无资料时凭参数化知识编造维修步骤。

设计原则（与项目安全观一致：提示词只做行为约束，不当安全边界）：
    本模块只提供纯函数判定，不调 LLM、不读环境、不做 IO，
    可在毫秒级完成且单测完全确定。调用方负责在图节点中挂载并替换回复。

判定口径：
    用途禁区/越权校准采用「输入命中话题 AND 输出无拒答信号」双条件。
    只命中话题不拦截，允许模型引用语料正确拒答（如 GR03 防爆题输出
    「禁止在 0 区使用」即放行）；只有该拒而未拒时才替换标准话术，
    把误伤面压到最小。库外问题的触发信号由调用方按检索证据判定，
    本模块只提供标准话术常量。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 话题类型常量
TOPIC_MEDICAL = "medical_temperature"
TOPIC_FLAME = "flame_temperature"
TOPIC_EXPLOSION = "explosion_zone"
TOPIC_CALIBRATION_BYPASS = "calibration_bypass"

#: 未命中任何受保护话题
TOPIC_NONE = ""


@dataclass(frozen=True)
class TopicGuardResult:
    """护栏判定结果。

    blocked=True 时调用方应使用 response 替换模型原始输出，
    并清空引用、按拒答落库（answer_status=refused）。
    """

    blocked: bool
    topic: str
    reason: str
    response: str


# ---------------------------------------------------------------------------
# 话题词表（仅按用户输入判定；词表与 data/docs 语料 12.2/FAQ Q24 口径对齐）
# ---------------------------------------------------------------------------

#: 人体医疗测温。注意「测锅炉外壁」合法，故火焰组词只收半透明气体本体，
#: 不收「锅炉/炉膛」容器词；医疗组词收测温用途与部位，不收「人体工学」类。
#: 「体温」不放进通用子串词表，单独走 _has_body_temperature_term 判定，
#: 否则会误伤「黑体温度 / 物体温度 / 气体温度」等物理量（GF08 回归）。
_MEDICAL_TERMS = (
    "发烧",
    "发热",
    "退烧",
    "额头",
    "额温",
    "手腕温度",
    "耳温",
    "腋下",
    "人体测温",
    "测人体",
    "医疗诊断",
    "医用",
    "筛查发热",
)

#: 「体温」前一字为这些字时是物理量子串，不算医疗语义。
_PHYSICAL_TEMP_PREFIX = ("黑", "物", "气")

_FLAME_TERMS = (
    "火焰",
    "明火",
    "火苗",
    "火舌",
    "烟气温度",  # 烟气同样为半透明介质，红外无法直测
)

_EXPLOSION_TERMS = (
    "防爆",
    "爆炸性气体",
    "爆炸危险",
    "0区",
    "1区",
    "2区",
    "ex认证",
    "ex 认证",
    "本质安全",
    "粉尘爆炸",
)

#: 越权校准采用 A×B 组合判定，避免「正常校准周期咨询」被误伤。
#: A 组为受保护入口/授权语义
_CAL_ENTRY_TERMS = (
    "校准模式",
    "授权密码",
    "校准密码",
    "工厂模式",
    "工程模式",
    "维修模式",
    "service mode",
    "calibration mode",
)
#: B 组为受保护内部参数（语料 FAQ Q24：私自修改导致永久失准）
_CAL_PARAM_TERMS = (
    "增益系数",
    "增益",
    "零点偏移",
    "零点漂移",
    "偏移量",
    "修正系数",
    "斜率系数",
    "gain",
    "offset",
)

#: 输出侧拒答软信号：出现任一则认为模型已正确收口，护栏放行。
#: 与 tests/golden/questions.yaml refusal.hedge_any 口径保持一致并略宽。
HEDGE_MARKERS = (
    "不能",
    "无法",
    "不适用",
    "不可以",
    "不得",
    "禁止",
    "严禁",
    "切勿",
    "请勿",
    "不应",
    "不要自行",
    "不建议",
    "不推荐",
    "不属于",
    "超出",
    "没有相关",
    "未收录",
    "无法准确",
)

# ---------------------------------------------------------------------------
# 标准话术（依据语料原文口径，含对应话题词与拒答信号，可过金标题库判分）
# ---------------------------------------------------------------------------

MEDICAL_RESPONSE = (
    "不能使用本仪器测量人体体温或用于发热筛查、医疗诊断。"
    "本仪器是工业级红外测温设备，其精度与算法不适用于人体测温，"
    "不能作为医疗设备使用，请使用专用医用测温设备。"
)

FLAME_RESPONSE = (
    "不能用本仪器准确测量火焰内部温度。火焰属于半透明气体，"
    "红外测温无法准确测量其内部温度，测量结果不具备参考价值。"
)

EXPLOSION_RESPONSE = (
    "普通版仪器没有防爆认证，禁止在 0 区、1 区等爆炸性气体环境使用，"
    "如需在该类环境作业，请选用具备对应防爆认证的专用设备。"
)

CALIBRATION_BYPASS_RESPONSE = (
    "不能指导您进入校准模式修改增益系数或零点偏移。校准模式受密码保护，"
    "须由授权计量人员配合专业设备操作；普通用户私自修改会破坏全量程线性、"
    "导致仪器永久失准且无法自行恢复。若示值超差，请联系厂家或授权计量机构"
    "返厂校准。"
)

#: 知识库外问题统一收口话术。GR05 实测：模型在无相关资料时会编造
#: 「断电重启、打开盖板」等步骤并挂无关引用，故收口时必须同时清空引用。
OUT_OF_SCOPE_RESPONSE = (
    "抱歉，您的问题超出了本工业测温设备知识库的覆盖范围，"
    "我在资料中没有找到相关内容，无法据此给出可靠回答，建议您联系人工客服。"
)

_STANDARD_RESPONSES = {
    TOPIC_MEDICAL: MEDICAL_RESPONSE,
    TOPIC_FLAME: FLAME_RESPONSE,
    TOPIC_EXPLOSION: EXPLOSION_RESPONSE,
    TOPIC_CALIBRATION_BYPASS: CALIBRATION_BYPASS_RESPONSE,
}


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def _has_body_temperature_term(text: str) -> bool:
    """检测医疗语义「体温」，排除物理测温子串碰撞（GF08）。

    「黑体温度 / 物体温度 / 气体温度」都含子串「体温」但属物理量。
    逐个扫描「体温」出现位置：前一字为 黑/物/气（物理前缀）的跳过；
    只要存在一个位于句首或前字非物理前缀的「体温」即判医疗。
    这样「黑体温度能测体温吗」这类混排仍会被拦截。
    """
    idx = 0
    while True:
        i = text.find("体温", idx)
        if i == -1:
            return False
        if i == 0 or text[i - 1] not in _PHYSICAL_TEMP_PREFIX:
            return True
        idx = i + 2


def detect_topic(user_input: str) -> str:
    """识别用户输入命中的受保护话题，未命中返回 TOPIC_NONE。

    越权校准要求「入口词 AND 内部参数词」同时出现，
    单独咨询校准周期、正常校准步骤不命中。
    """
    if not user_input:
        return TOPIC_NONE
    text = user_input.casefold()

    if _contains_any(text, _CAL_ENTRY_TERMS) and _contains_any(text, _CAL_PARAM_TERMS):
        return TOPIC_CALIBRATION_BYPASS
    if _contains_any(text, _MEDICAL_TERMS) or _has_body_temperature_term(text):
        return TOPIC_MEDICAL
    if _contains_any(text, _FLAME_TERMS):
        return TOPIC_FLAME
    if _contains_any(text, _EXPLOSION_TERMS):
        return TOPIC_EXPLOSION
    return TOPIC_NONE


def has_refusal_signal(text: str) -> bool:
    """模型输出是否已包含拒答软信号。"""
    if not text:
        return False
    return _contains_any(text, HEDGE_MARKERS)


def enforce_topic_guard(user_input: str, answer: str) -> TopicGuardResult:
    """话题硬闸门主入口。

    输入命中受保护话题且输出没有拒答信号时拦截，返回标准话术；
    其余情况（未命中话题、或模型已正确拒答）一律放行。
    """
    topic = detect_topic(user_input)
    if topic == TOPIC_NONE:
        return TopicGuardResult(False, TOPIC_NONE, "no_topic", answer or "")
    if has_refusal_signal(answer):
        return TopicGuardResult(False, topic, "already_refused", answer or "")
    return TopicGuardResult(
        blocked=True,
        topic=topic,
        reason=f"topic_hit_without_refusal:{topic}",
        response=_STANDARD_RESPONSES[topic],
    )
