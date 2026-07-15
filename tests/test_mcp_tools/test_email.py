"""Email MCP 工具测试（未启用模式 + MIME 解码逻辑）"""
import pytest
from unittest.mock import patch
from src.mcp_tools.email_tool import create_email_tools, _decode_mime_str


def _find(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise ValueError(f"Tool {name} not found")


class TestEmailDisabled:
    def test_disabled_returns_unenabled(self):
        with patch("src.mcp_tools.email_tool.settings") as mock_settings:
            mock_settings.mcp_email_enabled = False
            tools = create_email_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            assert len(tools) == 1
            result = tools[0].invoke({"to": "test@test.com", "subject": "t", "body": "b"})
            assert "[未启用]" in result
            assert "mcp_email_enabled" in result


class TestEmailEnabledTools:
    def test_enabled_tool_count(self):
        with patch("src.mcp_tools.email_tool.settings") as mock_settings:
            mock_settings.mcp_email_enabled = True
            mock_settings.mcp_email_smtp_host = "smtp.test.com"
            mock_settings.mcp_email_smtp_port = 587
            mock_settings.mcp_email_smtp_ssl = False
            mock_settings.mcp_email_imap_host = "imap.test.com"
            mock_settings.mcp_email_imap_port = 993
            mock_settings.mcp_email_imap_ssl = True
            mock_settings.mcp_email_username = "test@test.com"
            mock_settings.mcp_email_password = "pass"
            mock_settings.mcp_email_from_addr = "test@test.com"
            tools = create_email_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            assert len(tools) == 5

    def test_tool_names(self):
        with patch("src.mcp_tools.email_tool.settings") as mock_settings:
            mock_settings.mcp_email_enabled = True
            mock_settings.mcp_email_smtp_host = "smtp.test.com"
            mock_settings.mcp_email_smtp_port = 587
            mock_settings.mcp_email_smtp_ssl = False
            mock_settings.mcp_email_imap_host = "imap.test.com"
            mock_settings.mcp_email_imap_port = 993
            mock_settings.mcp_email_imap_ssl = True
            mock_settings.mcp_email_username = "test@test.com"
            mock_settings.mcp_email_password = "pass"
            mock_settings.mcp_email_from_addr = "test@test.com"
            tools = create_email_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            names = [t.name for t in tools]
            assert "email_send" in names
            assert "email_send_html" in names
            assert "email_list_inbox" in names
            assert "email_get_content" in names
            assert "email_search" in names


class TestDecodeMimeStr:
    def test_plain_text(self):
        assert _decode_mime_str("Hello World") == "Hello World"

    def test_empty_string(self):
        assert _decode_mime_str("") == ""

    def test_none(self):
        assert _decode_mime_str(None) == ""

    def test_utf8_base64(self):
        # Base64 编码的 "测试"
        encoded = "=?utf-8?b?5rWL6K+V?="
        result = _decode_mime_str(encoded)
        assert result in ["测试", "测试"]
