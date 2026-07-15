"""GitHub MCP 工具测试（未启用模式 + 仓库解析逻辑）"""
import pytest
from unittest.mock import patch
from src.mcp_tools.github import create_github_tools, _resolve_repo


def _find(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise ValueError(f"Tool {name} not found")


class TestGitHubDisabled:
    def test_disabled_returns_unenabled(self):
        with patch("src.mcp_tools.github.settings") as mock_settings:
            mock_settings.mcp_github_enabled = False
            tools = create_github_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            assert len(tools) == 1
            result = tools[0].invoke({"owner": "", "repo": ""})
            assert "[未启用]" in result
            assert "mcp_github_enabled" in result


class TestGitHubEnabledTools:
    def test_enabled_tool_count(self):
        with patch("src.mcp_tools.github.settings") as mock_settings:
            mock_settings.mcp_github_enabled = True
            mock_settings.mcp_github_token = "test_token"
            mock_settings.mcp_github_default_owner = "test_owner"
            mock_settings.mcp_github_default_repo = "test_repo"
            tools = create_github_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            assert len(tools) == 7

    def test_tool_names(self):
        with patch("src.mcp_tools.github.settings") as mock_settings:
            mock_settings.mcp_github_enabled = True
            mock_settings.mcp_github_token = "test_token"
            mock_settings.mcp_github_default_owner = "test_owner"
            mock_settings.mcp_github_default_repo = "test_repo"
            tools = create_github_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            names = [t.name for t in tools]
            assert "github_get_repo" in names
            assert "github_list_issues" in names
            assert "github_create_issue" in names
            assert "github_get_issue" in names
            assert "github_list_pulls" in names
            assert "github_get_file_content" in names
            assert "github_search_code" in names


class TestResolveRepo:
    def test_resolve_with_explicit_values(self):
        with patch("src.mcp_tools.github.settings") as mock_settings:
            mock_settings.mcp_github_default_owner = "default_owner"
            mock_settings.mcp_github_default_repo = "default_repo"
            owner, repo = _resolve_repo("myowner", "myrepo")
            assert owner == "myowner"
            assert repo == "myrepo"

    def test_resolve_with_defaults(self):
        with patch("src.mcp_tools.github.settings") as mock_settings:
            mock_settings.mcp_github_default_owner = "default_owner"
            mock_settings.mcp_github_default_repo = "default_repo"
            owner, repo = _resolve_repo("", "")
            assert owner == "default_owner"
            assert repo == "default_repo"

    def test_resolve_partial(self):
        with patch("src.mcp_tools.github.settings") as mock_settings:
            mock_settings.mcp_github_default_owner = "default_owner"
            mock_settings.mcp_github_default_repo = "default_repo"
            owner, repo = _resolve_repo("custom_owner", "")
            assert owner == "custom_owner"
            assert repo == "default_repo"
