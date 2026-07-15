"""PostgreSQL MCP 工具测试（未启用模式 + 只读 SQL 校验）"""
import pytest
from src.mcp_tools.postgres import _is_read_only_sql, create_postgres_tools


def _find(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise ValueError(f"Tool {name} not found")


@pytest.fixture()
def tools():
    return create_postgres_tools(
        user_id="admin_001", tenant_id="tenant_A", roles=["admin"], plan="enterprise"
    )


class TestIsReadOnlySql:
    def test_select_is_read_only(self):
        assert _is_read_only_sql("SELECT * FROM users") is True

    def test_select_with_where(self):
        assert _is_read_only_sql("select id, name from users where id = 1") is True

    def test_insert_is_not_read_only(self):
        assert _is_read_only_sql("INSERT INTO users VALUES (1, 'test')") is False

    def test_update_is_not_read_only(self):
        assert _is_read_only_sql("UPDATE users SET name = 'x' WHERE id = 1") is False

    def test_delete_is_not_read_only(self):
        assert _is_read_only_sql("DELETE FROM users WHERE id = 1") is False

    def test_drop_is_not_read_only(self):
        assert _is_read_only_sql("DROP TABLE users") is False

    def test_select_with_comment_attack(self):
        assert _is_read_only_sql("SELECT * FROM users; DROP TABLE users;--") is False

    def test_empty_sql(self):
        assert _is_read_only_sql("") is False


class TestPostgresDisabled:
    def test_disabled_returns_unenabled_message(self, tools):
        result = _find(tools, "pg_query").invoke({"sql": "SELECT 1"})
        assert "[未启用]" in result
        assert "mcp_pg_enabled" in result

    def test_disabled_tool_count(self, tools):
        assert len(tools) == 1
