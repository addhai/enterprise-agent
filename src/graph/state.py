from typing import Annotated, Any, List, Optional, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """LangGraph 对话状态"""

    # 对话消息列表（追加模式）
    messages: Annotated[List[BaseMessage], add_messages]

    # 当前识别的用户意图：faq | technical | human | unknown
    intent: Optional[str]

    # 动态 max_turns（根据意图复杂度调整）
    effective_max_turns: int

    # 是否已经做过 Reflection
    has_reflected: bool

    # RAG 检索到的文档
    retrieved_docs: Optional[List[Any]]

    # 是否触发转人工
    needs_human: bool

    # 当前对话轮次
    turn_count: int

    # 最终回复
    final_response: str

    # 用户 ID
    user_id: Optional[str]

    # 会话 ID（用于记忆管理）
    session_id: Optional[str]

    # 租户 ID（多租户隔离）
    tenant_id: Optional[str]

    # 用户权限等级列表
    user_access_levels: Optional[List[str]]

    # 用户角色列表（admin/developer/billing_manager）
    user_roles: Optional[List[str]]

    # 用户订阅计划（free/pro/enterprise）
    user_plan: Optional[str]

    # FAQ 匹配结果
    faq_match: Optional[str]

    # 记忆上下文（长期记忆 + 用户画像，由 entry_node 注入）
    memory_context: Optional[str]

    # 对话质量评估（reply_node 之后写入）
    quality_score: Optional[float]

    # 权限过滤数量（被过滤掉的文档数）
    access_filtered: Optional[int]

    # 注入式攻击拦截标记
    injection_blocked: bool

    # 攻击类型（仅在被拦截时）
    injection_type: Optional[str]

    # 是否需要专家委托（A2A 远程调用）
    needs_expert_delegation: bool

    # 专家回复内容
    expert_response: Optional[str]

    # 是否为闲聊（不走知识库检索）
    is_casual: bool
