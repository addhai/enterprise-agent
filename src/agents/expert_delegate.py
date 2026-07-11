"""专家委托节点 — A2A 远程委托

职责：
    当 CustomerServiceAgent 遇到超出知识库范围的问题时，
    通过 A2A 协议委托给远程专家 Agent（如性能专家、安全专家）。

触发条件：
    1. RAG 检索质量过低（quality_score < 0.3）
    2. Agent ReAct 循环达到 max_turns 仍未解决
    3. 用户明确提到特定领域（"性能问题"、"安全问题"）

回退策略：
    A2A 调用失败 → fallback_to_human → 转人工客服
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from src.config import settings
from src.protocols.a2a_server import delegate_to_expert

logger = logging.getLogger(__name__)


async def expert_delegate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """专家委托节点 — 异步执行

    如果满足委托条件，调用 A2A 委托给远程专家。
    委托成功则合并专家回复到 final_response。
    委托失败则标记需要转人工。

    Returns:
        包含 final_response 更新或 needs_human 标记的状态字典
    """
    # 检查是否需要委托
    if not state.get("needs_expert_delegation"):
        return {}

    query = ""
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        query = last.content if hasattr(last, "content") else str(last)

    if not query:
        return {"needs_expert_delegation": False}

    # 获取专家 Agent URL
    expert_url = settings.loader.a2a.expert_agent_url if hasattr(settings.loader.a2a, "expert_agent_url") else "http://localhost:9002"
    timeout = settings.loader.a2a.delegate_timeout if hasattr(settings.loader.a2a, "delegate_timeout") else 30

    logger.info("Delegating to expert agent: query=%s, url=%s", query[:100], expert_url)

    try:
        # 异步委托
        expert_response = await asyncio.wait_for(
            delegate_to_expert(query=query, expert_agent_url=expert_url, timeout=timeout),
            timeout=timeout + 5,  # 额外 5 秒缓冲
        )
    except asyncio.TimeoutError:
        logger.warning("Expert delegation timed out")
        expert_response = None
    except Exception as e:
        logger.error("Expert delegation failed: %s", e)
        expert_response = None

    if expert_response:
        logger.info("Expert delegation succeeded")
        return {
            "final_response": f"[专家回复]\n{expert_response}",
            "expert_response": expert_response,
            "needs_expert_delegation": False,
        }
    else:
        # 委托失败 → 回退到转人工
        logger.warning("Expert delegation failed, falling back to human")
        fallback = settings.loader.a2a.fallback_to_human if hasattr(settings.loader.a2a, "fallback_to_human") else True
        if fallback:
            return {
                "final_response": "抱歉，我无法处理您的技术问题。正在为您转接人工客服。",
                "needs_human": True,
                "needs_expert_delegation": False,
            }
        return {
            "needs_expert_delegation": False,
        }
