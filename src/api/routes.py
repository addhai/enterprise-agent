"""
API 路由定义
"""
import uuid
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from src.graph.state import AgentState
from src.api.dependencies import get_workflow

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    """对话请求"""
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    session_id: Optional[str] = Field(None, description="会话 ID")
    user_id: Optional[str] = Field("anonymous", description="用户 ID")
    tenant_id: Optional[str] = Field("", description="租户 ID（多租户隔离）")
    user_access_levels: Optional[List[str]] = Field(
        None, description="用户权限等级列表，如 [\"public\", \"internal\"]"
    )
    user_roles: Optional[List[str]] = Field(
        None, description="用户角色列表，如 [\"admin\", \"developer\"]"
    )
    user_plan: Optional[str] = Field(
        "free", description="用户订阅计划（free/pro/enterprise）"
    )


class ChatResponse(BaseModel):
    """对话响应"""
    session_id: str
    reply: str
    needs_human: bool
    suggest_human: bool = False
    intent: Optional[str] = None


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "enterprise-agent"}


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """同步对话接口"""
    session_id = request.session_id or str(uuid.uuid4())

    try:
        app = get_workflow()

        state = AgentState(
            messages=[HumanMessage(content=request.message)],
            intent=None,
            retrieved_docs=[],
            needs_human=False,
            turn_count=0,
            final_response="",
            user_id=request.user_id or "anonymous",
            session_id=session_id,
            tenant_id=request.tenant_id or "",
            user_access_levels=request.user_access_levels or [
                "public", "internal", "confidential", "restricted"
            ],
            user_roles=request.user_roles or [],
            user_plan=request.user_plan or "free",
            faq_match=None,
            effective_max_turns=5,
            has_reflected=False,
            memory_context="",
            quality_score=None,
            access_filtered=0,
            needs_expert_delegation=False,
            expert_response=None,
            injection_blocked=False,
            injection_type=None,
            failed_attempts=0,
            suggest_human=False,
        )

        result = app.invoke(
            state,
            config={"configurable": {"thread_id": session_id}}
        )

        # 权限过滤信息：如果被过滤了文档，提示用户
        access_filtered = result.get("access_filtered", 0)
        reply = result.get("final_response", "")
        
        logger.info(f"Raw final_response starts with: {reply[:100]}")
        
        # 清理：过滤掉 Agent 内部的 ReAct 格式标记
        if reply:
            import re
            # 方法1：查找 Final Answer: 的位置，只保留其后的内容
            final_answer_match = re.search(r'Final Answer:\s*', reply, flags=re.IGNORECASE)
            logger.info(f"Final Answer match found: {final_answer_match is not None}")
            if final_answer_match:
                reply = reply[final_answer_match.end():]
            else:
                # 方法2：如果没有 Final Answer，查找最后一个内部标记之后的内容
                react_markers = ['Question:', 'Thought:', 'Action:', 'Action Input:', 'Observation:', 'Final Answer:']
                for marker in react_markers:
                    matches = list(re.finditer(re.escape(marker), reply, flags=re.IGNORECASE))
                    if matches:
                        last_match = matches[-1]
                        candidate = reply[last_match.end():].strip()
                        if candidate and not any(candidate.startswith(m) for m in react_markers):
                            reply = candidate
                            break
                else:
                    # 方法3：直接删除所有内部标记及其内容
                    reply = re.sub(r'(Question:|Thought:|Action:|Action Input:|Observation:).*?(?=\n\n|\n|$)', '', reply, flags=re.DOTALL | re.IGNORECASE)
            reply = reply.strip()
            reply = re.sub(r'\n{3,}', '\n\n', reply)
        
        logger.info(f"Cleaned reply: {reply[:100]}")

        if access_filtered > 0:
            reply += f"\n\n[注：本次检索有 {access_filtered} 条结果因权限不足被过滤]"

        # 记录业务指标
        try:
            from src.evaluation.tracker import get_evaluation_tracker
            tracker = get_evaluation_tracker()
            import time
            end_time = time.time()
            quality_score = result.get("quality_score")
            intent = result.get("intent", "unknown")
            turn_count = result.get("turn_count", 1)
            needs_human = result.get("needs_human", False)
            suggest_human = result.get("suggest_human", False)
            resolved = not needs_human and quality_score is not None and quality_score > 0.3
            tracker.record_chat(
                session_id=session_id,
                intent=intent,
                latency_ms=0,
                quality_score=quality_score,
                needs_human=needs_human,
                suggest_human=suggest_human,
                turn_count=turn_count,
                resolved=resolved,
            )
        except Exception as e:
            logger.warning("Failed to record metrics: %s", e)

        return ChatResponse(
            session_id=session_id,
            reply=reply,
            needs_human=result.get("needs_human", False),
            suggest_human=result.get("suggest_human", False),
            intent=result.get("intent"),
        )

    except Exception as e:
        logger.exception(f"Error processing chat: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)[:200]}")
