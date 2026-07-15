"""文件系统 MCP 工具测试（沙箱模式）"""
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from src.mcp_tools.filesystem import create_filesystem_tools


def _find(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise ValueError(f"Tool {name} not found")


@pytest.fixture()
def temp_root(tmp_path):
    """创建临时沙箱目录"""
    root = tmp_path / "fs_mount"
    root.mkdir()
    return root


@pytest.fixture()
def admin_tools(temp_root):
    with patch("src.mcp_tools.filesystem.settings") as mock_settings:
        mock_settings.mcp_fs_enabled = True
        mock_settings.mcp_fs_root_dir = str(temp_root)
        mock_settings.mcp_fs_allow_write = True
        tools = create_filesystem_tools(
            user_id="admin_001", tenant_id="tenant_A", roles=["admin"], plan="enterprise"
        )
        yield tools


@pytest.fixture()
def read_only_tools(temp_root):
    with patch("src.mcp_tools.filesystem.settings") as mock_settings:
        mock_settings.mcp_fs_enabled = True
        mock_settings.mcp_fs_root_dir = str(temp_root)
        mock_settings.mcp_fs_allow_write = False
        tools = create_filesystem_tools(
            user_id="admin_001", tenant_id="tenant_A", roles=["admin"], plan="enterprise"
        )
        yield tools


@pytest.fixture()
def user_tools(temp_root):
    with patch("src.mcp_tools.filesystem.settings") as mock_settings:
        mock_settings.mcp_fs_enabled = True
        mock_settings.mcp_fs_root_dir = str(temp_root)
        mock_settings.mcp_fs_allow_write = True
        tools = create_filesystem_tools(
            user_id="user_001", tenant_id="tenant_A", roles=["user"], plan="enterprise"
        )
        yield tools


class TestFSDisabled:
    def test_disabled_returns_unenabled(self):
        with patch("src.mcp_tools.filesystem.settings") as mock_settings:
            mock_settings.mcp_fs_enabled = False
            tools = create_filesystem_tools(
                user_id="u1", tenant_id="t1", roles=["admin"], plan="enterprise"
            )
            assert len(tools) == 1
            result = tools[0].invoke({"path": "."})
            assert "[未启用]" in result


class TestFSListDir:
    def test_list_empty_dir(self, admin_tools):
        result = _find(admin_tools, "fs_list_dir").invoke({"path": "."})
        assert "[目录列表]" in result
        assert "0 项" in result

    def test_list_with_files(self, admin_tools, temp_root):
        (temp_root / "test.txt").write_text("hello")
        (temp_root / "subdir").mkdir()
        result = _find(admin_tools, "fs_list_dir").invoke({"path": "."})
        assert "[目录列表]" in result
        assert "test.txt" in result
        assert "subdir" in result

    def test_list_not_found(self, admin_tools):
        result = _find(admin_tools, "fs_list_dir").invoke({"path": "nonexistent"})
        assert "[未找到]" in result


class TestFSReadWrite:
    def test_write_and_read_file(self, admin_tools):
        result = _find(admin_tools, "fs_write_file").invoke({
            "path": "hello.txt",
            "content": "Hello World",
        })
        assert "[写入成功]" in result
        assert "hello.txt" in result

        result = _find(admin_tools, "fs_read_file").invoke({"path": "hello.txt"})
        assert "[读取成功]" in result
        assert "Hello World" in result

    def test_write_no_overwrite(self, admin_tools, temp_root):
        (temp_root / "exist.txt").write_text("original")
        result = _find(admin_tools, "fs_write_file").invoke({
            "path": "exist.txt",
            "content": "new content",
        })
        assert "[文件已存在]" in result
        assert (temp_root / "exist.txt").read_text() == "original"

    def test_write_overwrite(self, admin_tools, temp_root):
        (temp_root / "exist.txt").write_text("original")
        result = _find(admin_tools, "fs_write_file").invoke({
            "path": "exist.txt",
            "content": "new content",
            "overwrite": True,
        })
        assert "[写入成功]" in result
        assert (temp_root / "exist.txt").read_text() == "new content"

    def test_read_file_not_found(self, admin_tools):
        result = _find(admin_tools, "fs_read_file").invoke({"path": "nope.txt"})
        assert "[未找到]" in result

    def test_read_only_write_denied(self, read_only_tools):
        result = _find(read_only_tools, "fs_write_file").invoke({
            "path": "test.txt",
            "content": "test",
        })
        assert "[只读模式]" in result


class TestFSDelete:
    def test_delete_file(self, admin_tools, temp_root):
        (temp_root / "del.txt").write_text("to delete")
        result = _find(admin_tools, "fs_delete_file").invoke({"path": "del.txt"})
        assert "[删除成功]" in result
        assert not (temp_root / "del.txt").exists()

    def test_delete_not_found(self, admin_tools):
        result = _find(admin_tools, "fs_delete_file").invoke({"path": "nope.txt"})
        assert "[未找到]" in result

    def test_delete_read_only_denied(self, read_only_tools, temp_root):
        (temp_root / "test.txt").write_text("test")
        result = _find(read_only_tools, "fs_delete_file").invoke({"path": "test.txt"})
        assert "[只读模式]" in result


class TestFSMkdir:
    def test_mkdir_success(self, admin_tools, temp_root):
        result = _find(admin_tools, "fs_mkdir").invoke({"path": "newdir"})
        assert "[创建成功]" in result
        assert (temp_root / "newdir").is_dir()

    def test_mkdir_already_exists(self, admin_tools, temp_root):
        (temp_root / "existdir").mkdir()
        result = _find(admin_tools, "fs_mkdir").invoke({"path": "existdir"})
        assert "[已存在]" in result


class TestFSStat:
    def test_stat_file(self, admin_tools, temp_root):
        (temp_root / "stat.txt").write_text("stat test")
        result = _find(admin_tools, "fs_stat").invoke({"path": "stat.txt"})
        assert "[文件信息]" in result
        assert "文件" in result
        assert "stat.txt" in result

    def test_stat_not_found(self, admin_tools):
        result = _find(admin_tools, "fs_stat").invoke({"path": "nope.txt"})
        assert "[未找到]" in result


class TestFSSearch:
    def test_search_files(self, admin_tools, temp_root):
        (temp_root / "alpha.txt").write_text("a")
        (temp_root / "beta.txt").write_text("b")
        (temp_root / "gamma.md").write_text("g")

        result = _find(admin_tools, "fs_search").invoke({
            "pattern": "*.txt",
            "path": ".",
        })
        assert "[搜索结果]" in result
        assert "alpha.txt" in result
        assert "beta.txt" in result
        assert "gamma.md" not in result


class TestPathTraversal:
    def test_path_traversal_blocked(self, admin_tools):
        result = _find(admin_tools, "fs_read_file").invoke({"path": "../etc/passwd"})
        assert "路径越界" in result or "[路径错误]" in result


class TestToolCount:
    def test_enabled_tool_count(self, admin_tools):
        assert len(admin_tools) == 7
