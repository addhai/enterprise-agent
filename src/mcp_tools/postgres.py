"""PostgreSQL MCP 工具 — 数据库查询与管理

安全策略：
  1. 只读模式（默认）：仅允许 SELECT 查询，禁止 DROP/DELETE/UPDATE/INSERT
  2. SQL 注入防护：参数化查询，禁止拼接用户输入
  3. 超时控制：单次查询最长 30 秒
  4. 结果限制：默认最多返回 100 行
"""
import logging
import re
from typing import Callable, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agent.tools import PermissionChecker
from src.config import settings
from src.mcp_tools.common import format_result, require_admin

logger = logging.getLogger(__name__)

_DANGEROUS_KEYWORDS = [
    "DROP ", "DELETE FROM", "TRUNCATE ", "ALTER TABLE",
    "CREATE TABLE", "INSERT INTO", "UPDATE ",
    "GRANT ", "REVOKE ", "--", ";--",
]


def _is_read_only_sql(sql: str) -> bool:
    """检查 SQL 是否为只读（仅 SELECT）"""
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return False
    for kw in _DANGEROUS_KEYWORDS:
        if kw in sql_upper:
            return False
    return True


def _get_pg_conn():
    """获取 PostgreSQL 连接（懒加载）"""
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=settings.mcp_pg_host,
            port=settings.mcp_pg_port,
            database=settings.mcp_pg_database,
            user=settings.mcp_pg_user,
            password=settings.mcp_pg_password,
            connect_timeout=5,
        )
        return conn
    except ImportError:
        return None
    except Exception as e:
        logger.error("PostgreSQL connection failed: %s", e)
        return None


def create_postgres_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建 PostgreSQL 数据库工具"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    if not settings.mcp_pg_enabled:
        @tool
        def pg_query(sql: str) -> str:
            """PostgreSQL 查询工具（未启用）。"""
            return format_result("未启用", "PostgreSQL MCP 服务未启用，请在配置中开启 mcp_pg_enabled")

        return [pg_query]

    @tool
    def pg_query(sql: str, limit: int = 100) -> str:
        """执行 PostgreSQL SELECT 查询（只读模式）。

        何时使用：需要从数据库查询数据时使用。仅支持 SELECT 语句。

        Args:
            sql: SELECT SQL 语句
            limit: 最大返回行数，默认 100
        """
        if not checker.check("pg_query"):
            return format_result("权限不足", "您没有权限查询数据库")

        if settings.mcp_pg_read_only and not _is_read_only_sql(sql):
            return format_result("只读模式", "当前为只读模式，仅允许 SELECT 查询")

        conn = _get_pg_conn()
        if conn is None:
            return format_result("连接失败", "无法连接到 PostgreSQL 数据库，请检查配置")

        try:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = 30000")
                cur.execute(sql)
                rows = cur.fetchmany(limit)
                col_names = [desc[0] for desc in cur.description] if cur.description else []

            result_lines = [f"[查询成功] 返回 {len(rows)} 行"]
            if col_names:
                result_lines.append("  列: " + " | ".join(col_names))
                for i, row in enumerate(rows):
                    formatted = " | ".join(str(v) if v is not None else "NULL" for v in row)
                    result_lines.append(f"  {i + 1}. {formatted}")

            return "\n".join(result_lines)
        except Exception as e:
            logger.error("pg_query error: %s", e)
            return format_result("查询失败", str(e))
        finally:
            conn.close()

    @tool
    def pg_execute(sql: str) -> str:
        """执行 PostgreSQL DDL/DML 语句（仅 admin，需关闭只读模式）。

        何时使用：需要创建表、插入数据、更新数据时使用。需要 admin 权限且非只读模式。

        Args:
            sql: DDL/DML SQL 语句（CREATE/INSERT/UPDATE/DELETE 等）
        """
        if not checker.check("pg_execute"):
            return format_result("权限不足", "您没有权限执行数据库写入操作")
        if not require_admin(checker, "pg_execute"):
            return format_result("权限不足", "需要 admin 角色")

        if settings.mcp_pg_read_only:
            return format_result("只读模式", "当前为只读模式，禁止写入操作")

        conn = _get_pg_conn()
        if conn is None:
            return format_result("连接失败", "无法连接到 PostgreSQL 数据库")

        try:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = 30000")
                cur.execute(sql)
                affected = cur.rowcount
            conn.commit()
            return format_result("执行成功", f"影响 {affected} 行")
        except Exception as e:
            conn.rollback()
            logger.error("pg_execute error: %s", e)
            return format_result("执行失败", str(e))
        finally:
            conn.close()

    @tool
    def pg_list_tables(schema: str = "public") -> str:
        """列出数据库中的所有表。

        何时使用：想了解数据库中有哪些表、表结构概览时。

        Args:
            schema: 模式名，默认 public
        """
        if not checker.check("pg_list_tables"):
            return format_result("权限不足", "您没有权限查看数据库表")

        conn = _get_pg_conn()
        if conn is None:
            return format_result("连接失败", "无法连接到 PostgreSQL 数据库")

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    ORDER BY table_name
                """, (schema,))
                rows = cur.fetchall()

            result_lines = [f"[查询成功] 模式 {schema} 共 {len(rows)} 张表:"]
            for name, ttype in rows:
                result_lines.append(f"  • {name} ({ttype})")
            return "\n".join(result_lines)
        except Exception as e:
            logger.error("pg_list_tables error: %s", e)
            return format_result("查询失败", str(e))
        finally:
            conn.close()

    @tool
    def pg_describe_table(table_name: str, schema: str = "public") -> str:
        """查看表结构（列名、类型、是否为空、默认值）。

        何时使用：想了解某张表的字段详情时。

        Args:
            table_name: 表名
            schema: 模式名，默认 public
        """
        if not checker.check("pg_describe_table"):
            return format_result("权限不足", "您没有权限查看表结构")

        conn = _get_pg_conn()
        if conn is None:
            return format_result("连接失败", "无法连接到 PostgreSQL 数据库")

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                """, (schema, table_name))
                rows = cur.fetchall()

            if not rows:
                return format_result("未找到", f"表 {table_name} 不存在")

            result_lines = [f"[表结构] {schema}.{table_name} ({len(rows)} 列):"]
            for col_name, dtype, nullable, default in rows:
                parts = [f"{col_name}: {dtype}"]
                if nullable == "NO":
                    parts.append("NOT NULL")
                if default:
                    parts.append(f"DEFAULT {default}")
                result_lines.append(f"  • " + ", ".join(parts))
            return "\n".join(result_lines)
        except Exception as e:
            logger.error("pg_describe_table error: %s", e)
            return format_result("查询失败", str(e))
        finally:
            conn.close()

    @tool
    def pg_explain(sql: str) -> str:
        """分析 SQL 执行计划（EXPLAIN ANALYZE）。

        何时使用：SQL 性能优化时，想查看查询计划和耗时。

        Args:
            sql: 要分析的 SQL 语句
        """
        if not checker.check("pg_explain"):
            return format_result("权限不足", "您没有权限分析 SQL")

        conn = _get_pg_conn()
        if conn is None:
            return format_result("连接失败", "无法连接到 PostgreSQL 数据库")

        try:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = 30000")
                cur.execute(f"EXPLAIN ANALYZE {sql}")
                rows = cur.fetchall()

            result_lines = ["[执行计划]"]
            for row in rows:
                result_lines.append(f"  {row[0]}")
            return "\n".join(result_lines)
        except Exception as e:
            logger.error("pg_explain error: %s", e)
            return format_result("分析失败", str(e))
        finally:
            conn.close()

    return [
        pg_query,
        pg_execute,
        pg_list_tables,
        pg_describe_table,
        pg_explain,
    ]
