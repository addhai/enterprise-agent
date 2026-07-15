"""MCP Client 和 Slack MCP 工具测试"""
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# MCP Client 测试
# ---------------------------------------------------------------------------

class TestMcpClientWrapper:
    """测试 MCP Client 包装器（zeromcp 未安装时的行为）"""

    def test_mcp_client_import_without_zeromcp(self):
        """MCP Client 模块应能在 zeromcp 未安装时正常导入"""
        from src.protocols.mcp_client import McpClient, _MCP_CLIENT_AVAILABLE
        assert McpClient is not None
        assert _MCP_CLIENT_AVAILABLE is False

    def test_mcp_client_raises_without_zeromcp(self):
        """zeromcp 未安装时调用客户端应抛出 RuntimeError"""
        from src.protocols.mcp_client import McpClient

        client = McpClient("http://localhost:9000/mcp")
        with pytest.raises(RuntimeError, match="zeromcp 未安装"):
            client._get_client()

    def test_mcp_client_initialize_false_without_zeromcp(self):
        """zeromcp 未安装时 initialize 应返回 False"""
        from src.protocols.mcp_client import McpClient

        client = McpClient("http://localhost:9000/mcp")
        result = client.initialize()
        assert result is False

    def test_mcp_client_discover_tools_empty_without_zeromcp(self):
        """zeromcp 未安装时 discover_tools 应返回空列表"""
        from src.protocols.mcp_client import McpClient

        client = McpClient("http://localhost:9000/mcp")
        tools = client.discover_tools()
        assert tools == []

    def test_mcp_client_call_tool_none_without_zeromcp(self):
        """zeromcp 未安装时 call_tool 应返回 None"""
        from src.protocols.mcp_client import McpClient

        client = McpClient("http://localhost:9000/mcp")
        result = client.call_tool("test_tool", {"arg": "value"})
        assert result is None

    def test_call_external_mcp_tool_none_without_zeromcp(self):
        """zeromcp 未安装时 call_external_mcp_tool 应返回 None"""
        from src.protocols.mcp_client import call_external_mcp_tool

        result = call_external_mcp_tool(
            "http://localhost:9000/mcp",
            "test_tool",
            {"arg": "value"},
        )
        assert result is None


# ---------------------------------------------------------------------------
# Slack MCP 工具测试
# ---------------------------------------------------------------------------

class TestSlackToolsDisabled:
    """测试 Slack MCP 工具禁用状态"""

    def test_slack_tools_disabled(self):
        """Slack 禁用时应返回提示工具"""
        with patch("src.config.settings.mcp_slack_enabled", False):
            from src.mcp_tools.slack import create_slack_tools
            tools = create_slack_tools(user_id="test_user")
            assert len(tools) == 1
            assert tools[0].name == "slack_send_message"
            result = tools[0].invoke({"channel": "#test", "text": "hello"})
            assert "未启用" in result

    def test_slack_tools_count(self):
        """Slack 启用时应返回 7 个工具"""
        with patch("src.config.settings.mcp_slack_enabled", True):
            with patch("src.config.settings.mcp_slack_token", "test-token"):
                from src.mcp_tools.slack import create_slack_tools
                tools = create_slack_tools(user_id="test_user")
                assert len(tools) == 7

    def test_slack_tool_names(self):
        """验证 Slack 工具名称"""
        with patch("src.config.settings.mcp_slack_enabled", True):
            with patch("src.config.settings.mcp_slack_token", "test-token"):
                from src.mcp_tools.slack import create_slack_tools
                tools = create_slack_tools(user_id="test_user")
                names = [t.name for t in tools]
                assert "slack_send_message" in names
                assert "slack_list_channels" in names
                assert "slack_get_channel_info" in names
                assert "slack_list_users" in names
                assert "slack_get_user_info" in names
                assert "slack_search_messages" in names
                assert "slack_create_channel" in names

    def test_slack_send_message_missing_params(self):
        """发送消息缺少参数时应返回错误"""
        with patch("src.config.settings.mcp_slack_enabled", True):
            with patch("src.config.settings.mcp_slack_token", "test-token"):
                from src.mcp_tools.slack import create_slack_tools
                tools = create_slack_tools(user_id="test_user")
                send_tool = [t for t in tools if t.name == "slack_send_message"][0]
                result = send_tool.invoke({"channel": "#test", "text": "hello"})
                assert "发送失败" in result or "未知错误" in result


# ---------------------------------------------------------------------------
# 外部 MCP 消费工具测试
# ---------------------------------------------------------------------------

class TestExternalMcpConsumptionTools:
    """测试客服 Agent 作为 Client 消费外部 MCP 的工具"""

    def test_call_external_github_tool_config_error(self):
        """GitHub MCP URL 未配置时应返回错误"""
        with patch("src.config.settings.mcp_client_github_url", ""):
            from src.protocols.mcp_client import call_external_mcp_tool
            from src.agent.tools import create_tools

            tools = create_tools(user_id="test_user")
            github_tool = [t for t in tools if "github" in t.name and "external" in t.name][0]
            result = github_tool.invoke({"tool_name": "github_get_repo", "arguments": '{"owner": "test"}'})
            assert "配置错误" in result
            assert "mcp_client_github_url" in result

    def test_call_external_slack_tool_config_error(self):
        """Slack MCP URL 未配置时应返回错误"""
        with patch("src.config.settings.mcp_client_slack_url", ""):
            from src.protocols.mcp_client import call_external_mcp_tool
            from src.agent.tools import create_tools

            tools = create_tools(user_id="test_user")
            slack_tool = [t for t in tools if "slack" in t.name and "external" in t.name][0]
            result = slack_tool.invoke({"tool_name": "slack_send_message", "arguments": '{"channel": "#test"}'})
            assert "配置错误" in result
            assert "mcp_client_slack_url" in result

    def test_call_external_tool_invalid_json(self):
        """参数不是有效 JSON 时应返回错误"""
        with patch("src.config.settings.mcp_client_github_url", "http://localhost:9000/mcp"):
            from src.agent.tools import create_tools

            tools = create_tools(user_id="test_user")
            github_tool = [t for t in tools if "github" in t.name and "external" in t.name][0]
            result = github_tool.invoke({"tool_name": "github_get_repo", "arguments": "invalid json"})
            assert "参数错误" in result
            assert "JSON" in result


# ---------------------------------------------------------------------------
# 客服 Agent 工具列表集成测试
# ---------------------------------------------------------------------------

class TestAgentExternalMcpIntegration:
    """测试外部 MCP 消费工具是否正确集成到客服 Agent"""

    def test_create_tools_includes_external_mcp_tools(self):
        """create_tools 应包含外部 MCP 消费工具"""
        from src.agent.tools import create_tools

        tools = create_tools(user_id="test_user")
        tool_names = [t.name for t in tools]
        assert "call_external_github_tool" in tool_names
        assert "call_external_slack_tool" in tool_names

    def test_create_tools_total_count_with_external_mcp(self):
        """总工具数：原有3 + A2A专家2 + 外部MCP消费2 = 7"""
        from src.agent.tools import create_tools

        tools = create_tools(user_id="test_user")
        assert len(tools) == 7

    def test_external_mcp_tool_descriptions(self):
        """外部 MCP 工具应有详细描述"""
        from src.agent.tools import create_tools

        tools = create_tools(user_id="test_user")
        github_tool = [t for t in tools if t.name == "call_external_github_tool"][0]
        slack_tool = [t for t in tools if t.name == "call_external_slack_tool"][0]

        assert "GitHub" in github_tool.description or "github" in github_tool.description.lower()
        assert "Slack" in slack_tool.description or "slack" in slack_tool.description.lower()
        assert "外部" in github_tool.description or "external" in github_tool.description.lower()
