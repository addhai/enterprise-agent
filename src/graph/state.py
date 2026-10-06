from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """LangGraph 对话状态"""

    # 对话消息列表（追加模式）
    messages: Annotated[list[BaseMessage], add_messages]

    # 当前识别的用户意图：faq | technical | human | unknown
    intent: str | None

    # 动态 max_turns（根据意图复杂度调整）
    effective_max_turns: int

    # 是否已经做过 Reflection
    has_reflected: bool

    # 最终回复是否来自云资源工具的真实返回（事实来源，跳过 reflect 二次改写）
    tool_sourced: bool

    # RAG 检索到的文档
    retrieved_docs: list[Any] | None

    # 是否触发转人工
    needs_human: bool

    # 当前对话轮次
    turn_count: int

    # 最终回复
    final_response: str

    # 用户 ID
    user_id: str | None

    # 会话 ID（用于记忆管理）
    session_id: str | None

    # 租户 ID（多租户隔离）
    tenant_id: str | None

    # 用户权限等级列表
    user_access_levels: list[str] | None

    # 用户角色列表（admin/developer/billing_manager）
    user_roles: list[str] | None

    # 用户订阅计划（free/pro/enterprise）
    user_plan: str | None

    # FAQ 匹配结果
    faq_match: str | None

    # 记忆上下文（长期记忆 + 用户画像，由 entry_node 注入）
    memory_context: str | None

    # 对话质量评估（reply_node 之后写入）
    quality_score: float | None

    # 权限过滤数量（被过滤掉的文档数）
    access_filtered: int | None

    # 注入式攻击拦截标记
    injection_blocked: bool

    # 攻击类型（仅在被拦截时）
    injection_type: str | None

    # 连续无法回答的次数（用于判断是否建议转人工）
    failed_attempts: int

    # 是否建议转人工（供前端显示按钮，用户点击后才真正转人工）
    suggest_human: bool

    # ===== HITL (Human-in-the-loop) 相关字段 =====
    # 是否正在等待人工介入
    awaiting_human: bool

    # 人工转接上下文（推送给人工客服的完整信息）
    human_handoff_context: dict[str, Any] | None

    # 人工客服的回复
    human_response: str | None

    # 处理该任务的人工客服 ID
    human_agent_id: str | None

    # 是否已由人工处理完成
    human_handled: bool

    # ===== Phase5 kb_call_mode 可观测性三要素（落 state 与日志，非 WS 必填） =====
    # 生效模式：always | smart | never（非法值已在 rag_node 回落 always）
    kb_call_mode: str | None

    # 检索判定来源：rule / score / score_reject / fallback / always / never
    retrieval_decided_by: str | None

    # 本次问答实际检索次数（含预检索/探测、Agent 自主检索、尾部补检）
    retrieval_count: int | None

    # 答案合成路径：direct_synthesis（高置信直答旁路）/ react_agent /
    # direct_no_retrieval（never 模式直答）
    answer_path: str | None
