"""
API 路由定义
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

import chromadb
from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.api.auth import get_current_user
from src.api.dependencies import get_workflow
from src.api.rbac import role_to_access_levels
from src.config import settings
from src.graph.state import AgentState

logger = logging.getLogger(__name__)
router = APIRouter()

# ollama 探测超时（秒）。整体预算须小于 docker-compose.prod.yml
# 健康探针的 5s timeout，ollama 是其中唯一走网络的探测项。
_DETAIL_BUDGET_OLLAMA = 2.0


class ChatRequest(BaseModel):
    """对话请求"""

    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    session_id: str | None = Field(None, description="会话 ID")
    user_id: str | None = Field("anonymous", description="用户 ID")
    tenant_id: str | None = Field("", description="租户 ID（多租户隔离）")
    user_access_levels: list[str] | None = Field(
        None, description='用户权限等级列表，如 ["public", "internal"]'
    )
    user_roles: list[str] | None = Field(
        None, description='用户角色列表，如 ["admin", "developer"]'
    )
    user_plan: str | None = Field(
        "free", description="用户订阅计划（free/pro/enterprise）"
    )


class ChatResponse(BaseModel):
    """对话响应"""

    session_id: str
    reply: str
    needs_human: bool
    suggest_human: bool = False
    intent: str | None = None


@router.get("/health")
async def health_check():
    """轻量健康检查（Docker 探针使用，必须始终快速返回）

    额外暴露 aliyun_demo_fallback：让调用方（前端/运维）能感知当前是否处于
    “云资源样本回退”模式，避免把样本数据误认为真实数据。详见
    src/mcp_tools/cloud_provider.py 的 FallbackProvider。

    依赖级明细（database / vector_store / ollama / models）在
    GET /api/v1/health/detail，避免每次探针都付出依赖探测开销。
    """
    aliyun_demo_fallback = os.environ.get("ALIYUN_DEMO_FALLBACK", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    return {
        "status": "ok",
        "service": "enterprise-agent",
        "aliyun_demo_fallback": aliyun_demo_fallback,
    }


def _ollama_base_url() -> str:
    """推导本地 ollama 服务地址。

    优先 OLLAMA_BASE_URL；其次从指向 11434 的 OpenAI 兼容基址反推；
    最后回落到与容器内 ollama 同机的默认地址。
    """
    raw = os.getenv("OLLAMA_BASE_URL", "").strip()
    if not raw and "11434" in settings.openai_api_base:
        parts = urlsplit(settings.openai_api_base)
        if parts.scheme and parts.netloc:
            raw = f"{parts.scheme}://{parts.netloc}"
    return (raw or "http://localhost:11434").rstrip("/")


def _check_database() -> str:
    """数据库连通性：SELECT 1，返回 ok / down。"""
    import sqlalchemy

    from src.db.engine import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("SELECT 1"))
    return "ok"


def _check_vector_store() -> str:
    """向量库可用性：目录不存在或集合为空记 empty，异常记 down。

    目录缺失时不创建 PersistentClient，避免探测动作在磁盘上生成空目录。
    """
    persist_dir = settings.chroma_persist_dir
    if not os.path.isdir(persist_dir):
        return "empty"
    client = chromadb.PersistentClient(path=persist_dir)
    collections = client.list_collections()
    total = sum(col.count() if hasattr(col, "count") else 0 for col in collections)
    return "ok" if total > 0 else "empty"


def _check_ollama() -> tuple[str, str]:
    """ollama 连通性与模型加载状态，返回 (ollama状态, models状态)。"""
    base = _ollama_base_url()
    if urlsplit(base).scheme not in ("http", "https"):
        raise ValueError(f"ollama url 协议非法（需 http/https）：{base}")
    # S310/B310 双豁免：scheme 已在上一行显式限定为 http/https，
    # 目标是本机受控的 ollama 服务，不存在 file: 读本地文件的风险。
    req = urllib.request.Request(  # noqa: S310
        f"{base}/api/tags",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(  # noqa: S310  # nosec B310
        req, timeout=_DETAIL_BUDGET_OLLAMA
    ) as resp:
        tags_data = json.loads(resp.read().decode("utf-8", "replace"))
    model_names = [m.get("name", "") for m in tags_data.get("models", [])]
    llm_tag = os.getenv("OLLAMA_LLM_TAG", "qwen2.5")
    embed_tag = os.getenv("OLLAMA_EMBED_TAG", "bge-m3")
    has_llm = any(llm_tag in m for m in model_names)
    has_embed = any(embed_tag in m for m in model_names)
    if has_llm and has_embed:
        return "ok", "ok"
    if has_llm or has_embed:
        return "ok", "partial"
    return "ok", "none"


@router.get("/health/detail")
async def health_detail():
    """依赖级健康明细：数据库 / 向量库 / ollama / 模型加载。

    任一核心依赖 down 或 ollama 不可达时 body.status=degraded；
    HTTP 状态码始终为 200，状态语义放在 body 内，避免 Docker 探针
    在依赖短暂抖动时把容器判成 unhealthy。明细接口供运维巡检与
    上线检查清单使用，不承担探针职责。
    """
    checks: dict[str, str] = {}
    t0 = time.perf_counter()

    try:
        checks["database"] = _check_database()
    except Exception as e:
        logger.warning("Health detail: database down: %s", e)
        checks["database"] = "down"

    try:
        checks["vector_store"] = _check_vector_store()
    except Exception as e:
        logger.warning("Health detail: vector_store down: %s", e)
        checks["vector_store"] = "down"

    try:
        checks["ollama"], checks["models"] = _check_ollama()
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as e:
        logger.warning("Health detail: ollama unreachable: %s", e)
        checks["ollama"] = "unreachable"
        checks["models"] = "none"

    degraded = any(v == "down" for v in checks.values()) or (
        checks.get("ollama") == "unreachable"
    )
    return {
        "status": "degraded" if degraded else "ok",
        "service": "enterprise-agent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """同步对话接口（需要登录）

    安全约束（2026-10 P0-1 收口 H1 跨租户越权）：
        user_id / tenant_id / user_access_levels / user_roles 一律以服务端
        验签后的 token 用户为唯一来源。请求体中的同名字段仅为向后兼容保留，
        服务端不读取、不采信，防止匿名调用自报租户与四级密级检索他租户知识库。
    """
    session_id = request.session_id or str(uuid.uuid4())

    # 身份三元组全部来自服务端，客户端无法通过请求体提权或串租户。
    server_user_id = current_user["user_id"]
    server_tenant_id = current_user.get("tenant_id") or "default"
    server_role = current_user.get("role", "viewer")
    server_access_levels = role_to_access_levels(server_role)

    try:
        app = get_workflow()

        state = AgentState(
            messages=[HumanMessage(content=request.message)],
            intent=None,
            retrieved_docs=[],
            needs_human=False,
            turn_count=0,
            final_response="",
            user_id=server_user_id,
            session_id=session_id,
            tenant_id=server_tenant_id,
            user_access_levels=server_access_levels,
            user_roles=[server_role],
            user_plan=request.user_plan or "free",
            faq_match=None,
            # 每次请求重新读取，使 max_reasoning_turns 的热更新立即生效。
            # 此处曾硬编码为 5，导致配置中心改了这个值也不起作用（假热更新）。
            effective_max_turns=getattr(settings, "max_reasoning_turns", 5),
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

        result = app.invoke(state, config={"configurable": {"thread_id": session_id}})

        # 权限过滤信息：如果被过滤了文档，提示用户
        access_filtered = result.get("access_filtered", 0)
        reply = result.get("final_response", "")

        logger.info(f"Raw final_response starts with: {reply[:100]}")

        # 清理：过滤掉 Agent 内部的 ReAct 格式标记
        if reply:
            import re

            # 方法1：查找 Final Answer: 的位置，只保留其后的内容
            final_answer_match = re.search(
                r"Final Answer:\s*", reply, flags=re.IGNORECASE
            )
            logger.info(f"Final Answer match found: {final_answer_match is not None}")
            if final_answer_match:
                reply = reply[final_answer_match.end() :]
            else:
                # 方法2：没有 Final Answer，取最后一个内部标记之后的内容
                react_markers = [
                    "Question:",
                    "Thought:",
                    "Action:",
                    "Action Input:",
                    "Observation:",
                    "Final Answer:",
                ]
                for marker in react_markers:
                    matches = list(
                        re.finditer(re.escape(marker), reply, flags=re.IGNORECASE)
                    )
                    if matches:
                        last_match = matches[-1]
                        candidate = reply[last_match.end() :].strip()
                        if candidate and not any(
                            candidate.startswith(m) for m in react_markers
                        ):
                            reply = candidate
                            break
                else:
                    # 方法3：直接删除所有内部标记及其内容
                    reply = re.sub(
                        r"(Question:|Thought:|Action:|Action Input:|Observation:)"
                        r".*?(?=\n\n|\n|$)",
                        "",
                        reply,
                        flags=re.DOTALL | re.IGNORECASE,
                    )
            reply = reply.strip()
            reply = re.sub(r"\n{3,}", "\n\n", reply)

        logger.info(f"Cleaned reply: {reply[:100]}")

        if access_filtered > 0:
            reply += f"\n\n[注：本次检索有 {access_filtered} 条结果因权限不足被过滤]"

        # 记录业务指标
        try:
            from src.evaluation.tracker import get_evaluation_tracker

            tracker = get_evaluation_tracker()
            quality_score = result.get("quality_score")
            intent = result.get("intent", "unknown")
            turn_count = result.get("turn_count", 1)
            needs_human = result.get("needs_human", False)
            suggest_human = result.get("suggest_human", False)
            resolved = (
                not needs_human and quality_score is not None and quality_score > 0.3
            )
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
        raise HTTPException(
            status_code=500, detail=f"Internal error: {str(e)[:200]}"
        ) from e
