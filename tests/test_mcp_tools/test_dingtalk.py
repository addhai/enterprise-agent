"""钉钉 MCP 工具测试（未启用模式 + Token 缓存逻辑）"""
import pytest
from unittest.mock import patch
from src.mcp_tools.dingtalk import create_dingtalk_tools, _access_token_cache


def _find(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise ValueError(f"Tool {name} not found")


@pytest.fixture(autouse=True)
def clear_token_cache():
    _access_token_cache["token"] = ""
    _access_token_cache["expires_at"] = 0
    yield


class TestDingtalkDisabled:
    def test_disabled_returns_unenabled(self):
        with patch("src.mcp_tools.dingtalk.settings") as mock_settings:
            mock_settings.mcp_dingtalk_enabled = False
            tools = create_dingtalk_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            assert len(tools) == 1
            result = tools[0].invoke({"user_id_list": "u1", "content": "test"})
            assert "[未启用]" in result
            assert "mcp_dingtalk_enabled" in result


class TestDingtalkEnabledTools:
    def test_enabled_tool_count(self):
        with patch("src.mcp_tools.dingtalk.settings") as mock_settings:
            mock_settings.mcp_dingtalk_enabled = True
            mock_settings.mcp_dingtalk_app_key = "test_key"
            mock_settings.mcp_dingtalk_app_secret = "test_secret"
            mock_settings.mcp_dingtalk_agent_id = "123456"
            tools = create_dingtalk_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            assert len(tools) == 6

    def test_tool_names(self):
        with patch("src.mcp_tools.dingtalk.settings") as mock_settings:
            mock_settings.mcp_dingtalk_enabled = True
            mock_settings.mcp_dingtalk_app_key = "test_key"
            mock_settings.mcp_dingtalk_app_secret = "test_secret"
            mock_settings.mcp_dingtalk_agent_id = "123456"
            tools = create_dingtalk_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            names = [t.name for t in tools]
            assert "dingtalk_send_text" in names
            assert "dingtalk_send_markdown" in names
            assert "dingtalk_send_action_card" in names
            assert "dingtalk_get_user_info" in names
            assert "dingtalk_list_departments" in names
            assert "dingtalk_get_department_users" in names
