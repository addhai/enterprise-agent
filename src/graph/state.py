from typing import Annotated, Any, List, Optional, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """LangGraph 对话状态"""

    # 对话消息列表（追加模式）
    messages: Annotated[List[BaseMessage], add_messages]

    # 当前识别的用户意图：faq | technical | human | unknown
    intent: Optional[str]

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

    # FAQ 匹配结果
    faq_match: Optional[str]
