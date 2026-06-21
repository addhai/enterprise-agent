"""Tests for the complete LangGraph workflow assembly"""
import pytest
import os
import tempfile
from langchain_core.messages import HumanMessage
from langchain_core.documents import Document
from src.graph.workflow import create_workflow
from src.graph.state import AgentState
from src.rag.retriever import HybridRetriever


@pytest.fixture
def workflow():
    """Create a workflow with a basic retriever"""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    retriever = None
    with tempfile.TemporaryDirectory() as tmpdir:
        r = HybridRetriever(persist_directory=tmpdir, collection_name="test_wf")
        r.index_documents([
            Document(page_content="To reset your API key, go to Developer Settings.",
                     metadata={"source": "api.md"}),
            Document(page_content="CloudSync pricing: Free, Pro ($15/mo), Enterprise ($50/user/mo).",
                     metadata={"source": "pricing.md"}),
        ])
        retriever = r
        app = create_workflow(retriever=retriever)
        yield app
        r.delete_collection()


def test_workflow_handles_faq(workflow):
    """Workflow should handle FAQ-type questions"""
    state = AgentState(
        messages=[HumanMessage(content="How do I reset my password?")],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
        user_id="test_user",
        faq_match=None,
    )

    result = workflow.invoke(state, config={"configurable": {"thread_id": "test-1"}})

    assert result["final_response"] is not None
    assert len(result["final_response"]) > 10


def test_workflow_handles_technical(workflow):
    """Workflow should handle technical troubleshooting questions"""
    state = AgentState(
        messages=[HumanMessage(content="How do I get an API key for the Python SDK?")],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
        user_id="test_user",
        faq_match=None,
    )

    result = workflow.invoke(state, config={"configurable": {"thread_id": "test-2"}})

    assert result["final_response"] is not None
    assert len(result["final_response"]) > 10


def test_workflow_handles_human_request(workflow):
    """Workflow should handle human transfer requests"""
    state = AgentState(
        messages=[HumanMessage(content="I want to speak to a human agent")],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
        user_id="test_user",
        faq_match=None,
    )

    result = workflow.invoke(state, config={"configurable": {"thread_id": "test-3"}})

    assert "转接" in result["final_response"] or "human" in result["final_response"].lower()
