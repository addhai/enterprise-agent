"""Reflect Handler — 四维质量审查

职责：
    对 Agent 的回复进行质量审查：
    1. 事实准确性 — 技术断言是否有依据
    2. 完整性 — 是否遗漏用户已尝试的步骤
    3. 安全性 — 是否包含危险指令或泄露内部信息
    4. 证据支撑 — 每个结论是否有对应文档依据

设计原则：
    - 仅在 intent=technical 时执行（非 FAQ 和非转人工）
    - 使用独立 LLM 实例，temperature=0.0（确定性输出）
    - 审查通过（PASS）则不修改回复，否则重写
    - 可独立部署为 A2A 技能

架构：
    reflect_handler(state) → { final_response (可能重写) | has_reflected=True }

    被父图直接调用，不作为独立子图
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langchain_openai import ChatOpenAI

from src.config import settings

logger = logging.getLogger(__name__)

_REFLECT_PROMPT = (
    "你是一个质量审查员。请检查以下客服 Agent 的回复，从四个角度审查：\n\n"
    "1. **事实准确性**：回复中的所有技术断言（API 名称、配置步骤、错误码、版本号）"
    "是否都有依据？如果有任何编造或猜测的内容，请指出。\n"
    "2. **完整性**：有没有遗漏用户已经尝试过的步骤？"
    "如果用户之前提到过排查信息，回复是否充分利用了这些信息？\n"
    "3. **安全性**：回复是否包含任何危险的指令（如删除数据、绕过安全措施）？"
    "是否泄露了系统内部信息（System Prompt、工具定义、其他用户信息）？\n"
    "4. **证据支撑**：回复中的每个技术结论是否有对应的文档依据？"
    "如果结论无法从检索文档中直接推导，标记为证据不足。\n\n"
    "【Agent 回复】\n{response}\n\n"
    "请给出审查结论。如果有问题，直接输出修正后的完整回复。"
    "如果回复没有问题，输出 'PASS'。"
)


def reflect_handler(state: Dict[str, Any]) -> Dict[str, Any]:
    """质检处理节点：LLM 四维审查

    对 final_response 进行事实准确性、完整性、安全性、证据支撑的检查。
    审查通过返回 "PASS"，否则返回修正后的回复。
    """
    final_response = state.get("final_response", "")
    if not final_response:
        return {"has_reflected": True, "needs_rewrite": False}

    # 仅在 quality_score 不确定时才调用 LLM 审查
    quality_score = state.get("quality_score")
    if quality_score is not None and quality_score >= 0.8:
        # 高质量回复直接通过
        return {"has_reflected": True, "needs_rewrite": False}

    reflect_llm = ChatOpenAI(
        model=settings.llm_safety,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        temperature=0.0,
    )

    try:
        prompt = _REFLECT_PROMPT.format(response=final_response)
        result = reflect_llm.invoke(prompt)
        reflection_output = result.content.strip()
    except Exception as e:
        logger.warning("Reflection LLM call failed: %s", e)
        return {"has_reflected": True, "needs_rewrite": False}

    if reflection_output and reflection_output != "PASS":
        logger.info("Reflection produced revision")
        return {
            "final_response": reflection_output,
            "has_reflected": True,
            "needs_rewrite": True,
            "reflection_notes": f"Revision: {reflection_output[:200]}",
        }

    logger.debug("Reflection passed")
    return {
        "has_reflected": True,
        "needs_rewrite": False,
        "reflection_notes": "PASS",
    }
