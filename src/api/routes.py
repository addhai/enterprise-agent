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
        )

        result = app.invoke(
            state,
            config={"configurable": {"thread_id": session_id}}
        )

        # 权限过滤信息：如果被过滤了文档，提示用户
        access_filtered = result.get("access_filtered", 0)
        reply = result.get("final_response", "")
        if access_filtered > 0:
            reply += f"\n\n[注：本次检索有 {access_filtered} 条结果因权限不足被过滤]"

        return ChatResponse(
            session_id=session_id,
            reply=reply,
            needs_human=result.get("needs_human", False),
            intent=result.get("intent"),
        )

    except Exception as e:
        logger.exception(f"Error processing chat: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)[:200]}")
