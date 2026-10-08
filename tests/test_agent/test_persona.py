"""人设收口回归（2026-10-06）

防止 CloudSync SaaS 人设回潮：
1. ReAct / 直答 system prompt 不得出现旧 SaaS 品牌与网盘产品
2. 云资源工具必须有「仅用户明确查自己云资源」的路由边界
3. 静态 FAQ 库只保留会话类/账号类通用应答，SaaS 事实条目不得复活
"""

from src.agent.prompt import REACT_SYSTEM_PROMPT
from src.agent.tools import _FAQ_STORE, _faq_search
from src.graph.nodes import _DIRECT_ANSWER_SYSTEM_PROMPT

# ---- 提示词口径 -----------------------------------------------------------


def test_react_prompt_is_industrial_device_persona():
    """ReAct 人设应为工业设备技术支持，不含旧 SaaS 品牌与网盘产品"""
    assert "工业设备" in REACT_SYSTEM_PROMPT
    for banned in ("CloudSync", "Google Drive", "Dropbox", "OneDrive", "S3"):
        assert banned not in REACT_SYSTEM_PROMPT, f"人设提示词残留旧品牌: {banned}"


def test_react_prompt_guards_cloud_resource_tools():
    """设备问题禁止误调云资源工具（F02 误路由根因的提示词约束）"""
    assert "query_resources" in REACT_SYSTEM_PROMPT
    assert "describe_resource" in REACT_SYSTEM_PROMPT
    assert "明确" in REACT_SYSTEM_PROMPT
    assert "禁止调用云资源工具" in REACT_SYSTEM_PROMPT


def test_direct_answer_prompt_has_no_saas_brand():
    """直答旁路提示词同样不得泄漏旧品牌"""
    assert "CloudSync" not in _DIRECT_ANSWER_SYSTEM_PROMPT


def test_direct_answer_prompt_requires_complete_coverage():
    """直答提示词必须含完整性硬条款（2026-10-08 金标 7B 要点遗漏归因）

    7B 旧版把「简洁直接」执行成提前收尾，条款必须具体可执行，
    不能只写一句「要完整」。
    """
    assert "完整性优先于简短" in _DIRECT_ANSWER_SYSTEM_PROMPT
    assert "逐点作答" in _DIRECT_ANSWER_SYSTEM_PROMPT
    assert "禁止中途收尾" in _DIRECT_ANSWER_SYSTEM_PROMPT
    assert "列出所有档位" in _DIRECT_ANSWER_SYSTEM_PROMPT
    assert "先解释代码含义" in _DIRECT_ANSWER_SYSTEM_PROMPT
    # 资料已给判据时禁止声称未给出（GP04 稳定判据漏写根因）
    assert "禁止回答「未明确给出」" in _DIRECT_ANSWER_SYSTEM_PROMPT
    # 完整性条款不得破坏无覆盖拒答兜底
    assert "资料中未找到该问题的相关信息" in _DIRECT_ANSWER_SYSTEM_PROMPT
    # few-shot 具体范例已于 2026-10-08 证伪：7B 照抄虚构事实污染真实答案
    # （汽油/松香水禁忌被搬进 F01 答案），规则约束版不得复活问答范例
    assert "回答格式示范" not in _DIRECT_ANSWER_SYSTEM_PROMPT
    assert "汽油" not in _DIRECT_ANSWER_SYSTEM_PROMPT
    for real_model in ("T90", "T100", "ThermoView", "ThermoSense"):
        assert real_model not in _DIRECT_ANSWER_SYSTEM_PROMPT


def test_react_prompt_requires_complete_coverage():
    """ReAct 提示词同步含完整性条款，且旧的「不要长篇大论」压垮"""
    assert "完整性优先于简短" in REACT_SYSTEM_PROMPT
    assert "逐点作答" in REACT_SYSTEM_PROMPT
    assert "禁止提前收尾" in REACT_SYSTEM_PROMPT
    assert "不得声称「未明确给出」" in REACT_SYSTEM_PROMPT
    assert "不要长篇大论" not in REACT_SYSTEM_PROMPT


# ---- 静态 FAQ 库边界 -------------------------------------------------------


def test_faq_store_keeps_conversational_and_password_entries():
    """问候/感谢/再见/重置密码仍由静态库承接"""
    assert _faq_search("你好") is not None
    assert _faq_search("谢谢") is not None
    assert _faq_search("再见") is not None
    assert _faq_search("如何重置密码") is not None
    assert _faq_search("reset password") is not None


def test_faq_store_rejects_saas_factual_entries():
    """纯 SaaS 事实条目已删除，命中不了静态库（应回落知识库/LLM 路径）"""
    for query in (
        "怎么变更套餐",
        "如何取消订阅",
        "我的同步失败了",
        "你们的定价是多少",
        "怎么配置 SSO",
        "如何开启双因素认证",
        "403 错误怎么办",
    ):
        assert _faq_search(query) is None, f"该 SaaS 条目不应存在: {query}"


def test_faq_store_contains_no_brand_leak():
    """任何静态 FAQ 答案都不得带具体品牌名"""
    for item in _FAQ_STORE:
        assert "CloudSync" not in item["answer"]
        assert "千问" not in item["answer"]
