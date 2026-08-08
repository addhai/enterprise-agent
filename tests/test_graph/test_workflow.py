"""Tests for the complete LangGraph workflow assembly"""
import pytest
import os
import shutil
import tempfile
from langchain_core.messages import HumanMessage
from langchain_core.documents import Document
from src.graph.workflow import create_workflow
from src.graph.state import AgentState
from src.rag.retriever import HybridRetriever


@pytest.fixture
def workflow():
    """Create a workflow with a basic retriever"""
    # 加载 .env 文件使 OPENAI_API_KEY 生效
    from dotenv import load_dotenv
    load_dotenv()

    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    # 注意：不能用 with TemporaryDirectory()，Chroma 在退出时仍持有 sqlite 文件句柄，
    # Windows 下会抛 PermissionError(WinError 32)。改为手动创建 + 容错清理。
    tmpdir = tempfile.mkdtemp(prefix="test_wf_")
    r = HybridRetriever(persist_directory=tmpdir, collection_name="test_wf")
    r.index_documents([
        Document(page_content="To reset your API key, go to Developer Settings.",
                 metadata={"source": "api.md"}),
        Document(page_content="CloudSync pricing: Free, Pro ($15/mo), Enterprise ($50/user/mo).",
                 metadata={"source": "pricing.md"}),
    ])
    app = create_workflow(retriever=r)
    try:
        yield app
    finally:
        try:
            r.delete_collection()
        except Exception:
            pass
        # 句柄未释放时忽略残留目录，不让清理失败污染测试结果
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.requires_llm
def test_workflow_handles_faq(workflow):
    """Workflow should handle FAQ-type questions（真实 LLM 路径，需 RUN_LLM_TESTS=1）"""
    state = AgentState(
        messages=[HumanMessage(content="How do I reset my password?")],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
        user_id="test_user",
        session_id="test-session-1",
        tenant_id="",
        user_access_levels=["public", "internal", "confidential", "restricted"],
        faq_match=None,
        effective_max_turns=5,
        has_reflected=False,
        memory_context="",
        quality_score=None,
        access_filtered=0,
    )

    result = workflow.invoke(state, config={"configurable": {"thread_id": "test-1"}})

    assert result["final_response"] is not None
    assert len(result["final_response"]) > 10


@pytest.mark.requires_llm
def test_workflow_handles_technical(workflow):
    """Workflow should handle technical troubleshooting questions（真实 LLM 路径，需 RUN_LLM_TESTS=1）"""
    state = AgentState(
        messages=[HumanMessage(content="How do I get an API key for the Python SDK?")],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
        user_id="test_user",
        session_id="test-session-2",
        tenant_id="",
        user_access_levels=["public", "internal", "confidential", "restricted"],
        faq_match=None,
        effective_max_turns=5,
        has_reflected=False,
        memory_context="",
        quality_score=None,
        access_filtered=0,
    )

    result = workflow.invoke(state, config={"configurable": {"thread_id": "test-2"}})

    assert result["final_response"] is not None
    assert len(result["final_response"]) > 10


@pytest.mark.requires_llm
def test_workflow_handles_human_request(workflow):
    """转人工请求应触发 HITL 中断，并在人工恢复后采用人工回复

    human_node 已重构为 interrupt() 中断节点，因此契约分两段：
    1) 首次 invoke 在 human 节点暂停，返回 __interrupt__ 且携带完整转接上下文
    2) 通过 Command(resume=...) 恢复后，人工回复应落到 final_response
    """
    from langgraph.types import Command

    config = {"configurable": {"thread_id": "test-3"}}
    state = AgentState(
        messages=[HumanMessage(content="I want to speak to a human agent")],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
        user_id="test_user",
        session_id="test-session-3",
        tenant_id="",
        user_access_levels=["public", "internal", "confidential", "restricted"],
        faq_match=None,
        effective_max_turns=5,
        has_reflected=False,
        memory_context="",
        quality_score=None,
        access_filtered=0,
    )

    # 第一段：应在 human 节点中断
    result = workflow.invoke(state, config=config)

    assert "__interrupt__" in result, "转人工请求未触发 HITL 中断"
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "human_handoff"
    # 中断必须把用户原话带给人工客服，否则坐席无法接手
    assert "speak to a human agent" in payload["context"]["user_message"]

    # 第二段：人工恢复后，回复应被采用
    human_reply = "您好，我是人工客服小李，已接手您的问题。"
    resumed = workflow.invoke(
        Command(resume={"response": human_reply, "agent_id": "agent-007"}),
        config=config,
    )

    assert human_reply in resumed["final_response"]
    assert resumed["human_agent_id"] == "agent-007"
    assert resumed["needs_human"] is False  # 人工已介入，不应再标记待转接
