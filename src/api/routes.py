"""
API 路由定义
"""
import uuid
import logging
from typing import Optional
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
            faq_match=None,
        )

        result = app.invoke(
            state,
            config={"configurable": {"thread_id": session_id}}
        )

        return ChatResponse(
            session_id=session_id,
            reply=result.get("final_response", ""),
            needs_human=result.get("needs_human", False),
            intent=result.get("intent"),
        )

    except Exception as e:
        logger.exception(f"Error processing chat: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)[:200]}")
