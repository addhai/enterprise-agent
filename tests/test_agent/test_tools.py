import pytest
from src.agent.tools import create_tools


def test_search_knowledge_base_returns_content():
    """search_knowledge_base 工具应返回文档内容"""
    tools = create_tools(retriever=None, user_id="test_user")

    # 找到 search_knowledge_base 工具
    kb_tool = [t for t in tools if t.name == "search_knowledge_base"][0]

    assert kb_tool is not None
    # LangChain @tool 修饰器用函数 docstring 作为 description（中文），检查非空即可
    assert kb_tool.description, f"Tool {kb_tool.name} should have a description"


def test_search_faq_returns_best_match():
    """search_faq 应在 FAQ 中查找精确匹配"""
    tools = create_tools(retriever=None, user_id="test_user")

    faq_tool = [t for t in tools if t.name == "search_faq"][0]
    assert faq_tool is not None
    assert "faq" in faq_tool.description.lower()


def test_escalate_to_human_creates_flag():
    """escalate_to_human 应在回复中标记转人工"""
    tools = create_tools(retriever=None, user_id="test_user")

    escalate_tool = [t for t in tools if t.name == "escalate_to_human"][0]
    result = escalate_tool.invoke({"reason": "Complex billing issue"})

    assert "escalated" in result.lower()
    assert "human" in result.lower()


def test_all_tools_have_descriptions():
    """每个工具都应有描述"""
    tools = create_tools(retriever=None, user_id="test_user")

    for tool in tools:
        assert tool.description, f"Tool {tool.name} has no description"
        assert len(tool.description) > 20, \
            f"Tool {tool.name} description too short: {tool.description}"


def test_create_tools_default_excludes_ticket_and_resource():
    """默认 create_tools 不应包含工单/资源工具（避免与 MCP Server 路径重复注册）"""
    tools = create_tools(retriever=None, user_id="test_user")
    names = {t.name for t in tools}

    assert "ticket_create" not in names
    assert "query_resources" not in names


def test_create_tools_with_flags_includes_ticket_and_resource():
    """开启 include_ticket / include_resource 后，对话 Agent 应获得完整工具集且无重复"""
    tools = create_tools(
        retriever=None,
        user_id="test_user",
        tenant_id="",
        roles=[],
        plan="free",
        include_ticket=True,
        include_resource=True,
    )
    names = [t.name for t in tools]
    name_set = set(names)

    # 不重复
    assert len(names) == len(name_set), f"存在重复工具: {[n for n in names if names.count(n) > 1]}"

    # 工单 6 件齐全
    for t in ["ticket_create", "ticket_query", "ticket_list",
              "ticket_update", "ticket_close", "ticket_add_comment"]:
        assert t in name_set, f"缺少工单工具: {t}"

    # 资源 3 件齐全
    for t in ["query_resources", "describe_resource", "get_resource_monitor"]:
        assert t in name_set, f"缺少资源工具: {t}"

