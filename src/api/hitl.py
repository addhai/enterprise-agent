"""HITL (Human-in-the-loop) 管理 API

供人工客服工作台使用：
    - 查询待处理的人工转接任务
    - 认领任务
    - 提交人工回复，恢复工作流

所有端点需要 admin / agent 角色。
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, Field

from src.api.rbac import require_roles, Role
from src.graph.hitl_manager import get_hitl_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["hitl"])


# ============ 请求 / 响应模型 ============

class ResumeRequest(BaseModel):
    """人工恢复工作流的请求"""
    response: str = Field(..., description="人工客服的回复内容")
    agent_id: Optional[str] = Field(None, description="处理该任务的人工客服 ID")


class AssignRequest(BaseModel):
    """认领任务的请求"""
    agent_id: str = Field(..., description="认领该任务的人工客服 ID")


# ============ 端点 ============

@router.get("/admin/hitl/pending")
async def list_pending_tasks(
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """列出所有等待人工介入的任务

    需要 admin 或 agent 角色
    """
    hitl = get_hitl_manager()
    tasks = await hitl.list_pending()

    # 脱敏 + 格式化返回
    result = []
    for t in tasks:
        interrupt_value = t.get("interrupt_value") or {}
        context = interrupt_value.get("context", {}) if isinstance(interrupt_value, dict) else {}
        result.append({
            "thread_id": t["thread_id"],
            "session_id": t["session_id"],
            "user_id": t.get("user_id", ""),
            "status": t["status"],
            "assigned_to": t.get("assigned_to"),
            "created_at": t["created_at"],
            "reason": context.get("reason", ""),
            "user_message": context.get("user_message", ""),
            "intent": context.get("intent"),
            "ai_suggested_response": context.get("ai_suggested_response", ""),
        })

    return {
        "total": len(result),
        "tasks": result,
    }


@router.get("/admin/hitl/{thread_id}")
async def get_task_detail(
    thread_id: str,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取单个待处理任务的完整上下文（含对话历史、检索文档）"""
    hitl = get_hitl_manager()
    task = await hitl.get_task(thread_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已完成")

    interrupt_value = task.get("interrupt_value") or {}
    context = interrupt_value.get("context", {}) if isinstance(interrupt_value, dict) else {}

    return {
        "thread_id": task["thread_id"],
        "session_id": task["session_id"],
        "user_id": task.get("user_id", ""),
        "status": task["status"],
        "assigned_to": task.get("assigned_to"),
        "created_at": task["created_at"],
        "context": context,
        "question": interrupt_value.get("question", "") if isinstance(interrupt_value, dict) else "",
    }


@router.post("/admin/hitl/{thread_id}/assign")
async def assign_task(
    thread_id: str,
    payload: AssignRequest,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """人工客服认领任务（防止多人同时处理同一任务）"""
    hitl = get_hitl_manager()
    agent_id = payload.agent_id or current_user.get("sub", "unknown")
    ok = await hitl.assign(thread_id, agent_id)
    if not ok:
        raise HTTPException(status_code=409, detail="任务不存在或已被他人认领")
    return {"status": "assigned", "assigned_to": agent_id}


@router.post("/admin/hitl/{thread_id}/resume")
async def resume_workflow(
    thread_id: str,
    payload: ResumeRequest,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """人工客服提交回复，恢复被暂停的工作流

    工作流从 human_node 的 interrupt() 处继续执行，
    拿到人工回复后走 reply → END。
    """
    hitl = get_hitl_manager()
    task = await hitl.get_task(thread_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已完成")

    # 自动认领（如果还没人认领）
    agent_id = payload.agent_id or current_user.get("sub", "unknown")
    if not task.get("assigned_to"):
        await hitl.assign(thread_id, agent_id)

    # 恢复工作流：传入人工回复
    try:
        from langgraph.types import Command
        from src.api.dependencies import get_workflow

        workflow = get_workflow()
        config = {"configurable": {"thread_id": thread_id}}

        # 用 Command(resume=...) 恢复，interrupt() 会拿到这个值
        resume_data = {
            "response": payload.response,
            "agent_id": agent_id,
        }

        if hasattr(workflow, "ainvoke"):
            result = await workflow.ainvoke(
                Command(resume=resume_data),
                config=config,
            )
        else:
            result = workflow.invoke(
                Command(resume=resume_data),
                config=config,
            )

        final_response = ""
        if isinstance(result, dict):
            final_response = result.get("final_response", "") or payload.response

        # 任务完成，从待处理列表移除
        await hitl.complete(thread_id)

        return {
            "status": "completed",
            "thread_id": thread_id,
            "final_response": final_response,
            "handled_by": agent_id,
        }
    except Exception as e:
        logger.exception("恢复工作流失败: thread=%s, error=%s", thread_id, e)
        raise HTTPException(status_code=500, detail=f"恢复工作流失败: {e}")


@router.post("/admin/hitl/cleanup")
async def cleanup_expired_tasks(
    max_age_seconds: int = 1800,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """清理超时的待处理任务（默认 30 分钟）

    仅 admin 可调用
    """
    hitl = get_hitl_manager()
    count = await hitl.cleanup_expired(max_age_seconds)
    return {"cleaned": count}
