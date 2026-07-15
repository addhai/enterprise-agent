"""知识库管理 MCP 工具测试 — 导入/重建索引/列表/删除/搜索"""
import pytest

from src.mcp_tools.kb import (
    create_kb_tools,
    _kb_store,
    KBItem,
    KBItemStatus,
)
from src.mcp_tools.common import current_utc_time, generate_id


@pytest.fixture(autouse=True)
def reset_store():
    _kb_store._store.clear()
    _kb_store._timestamps.clear()
    yield
    _kb_store._store.clear()
    _kb_store._timestamps.clear()


@pytest.fixture
def admin_tools():
    return create_kb_tools(
        user_id="admin_1",
        tenant_id="tenant_A",
        roles=["admin"],
    )


@pytest.fixture
def user_tools():
    return create_kb_tools(
        user_id="user_1",
        tenant_id="tenant_A",
        roles=[],
    )


def _find(tools, name):
    return [t for t in tools if t.name == name][0]


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------

def test_kb_tools_registered(admin_tools):
    names = {t.name for t in admin_tools}
    expected = {
        "kb_ingest_document",
        "kb_rebuild_index",
        "kb_list_items",
        "kb_delete_item",
        "kb_search",
    }
    assert expected.issubset(names)


# ---------------------------------------------------------------------------
# kb_ingest_document
# ---------------------------------------------------------------------------

def test_ingest_document_admin_success(admin_tools):
    """admin 可以导入文档"""
    result = _find(admin_tools, "kb_ingest_document").invoke({
        "file_path": "/docs/sso-guide.md",
        "title": "SSO 配置指南",
        "source_type": "document",
    })
    assert "[文档已导入]" in result
    assert "SSO 配置指南" in result
    assert "indexed" in result


def test_ingest_document_user_denied(user_tools):
    """普通用户不能导入"""
    result = _find(user_tools, "kb_ingest_document").invoke({
        "file_path": "/docs/test.md",
    })
    assert "[权限不足]" in result


def test_ingest_document_default_title(admin_tools):
    """未提供 title 时从文件名提取"""
    result = _find(admin_tools, "kb_ingest_document").invoke({
        "file_path": "/docs/api-docs.md",
    })
    assert "[文档已导入]" in result
    # 应从路径提取文件名作为标题
    assert "api-docs.md" in result


def test_ingest_document_url_source(admin_tools):
    """支持 url 来源"""
    result = _find(admin_tools, "kb_ingest_document").invoke({
        "file_path": "https://example.com/doc",
        "title": "在线文档",
        "source_type": "url",
    })
    assert "[文档已导入]" in result


def test_ingest_document_sets_indexed_status(admin_tools):
    """导入后状态应为 indexed"""
    _find(admin_tools, "kb_ingest_document").invoke({
        "file_path": "/docs/test.md",
        "title": "test",
    })
    items = _kb_store.list("tenant_A", 10)
    assert len(items) == 1
    assert items[0].status == KBItemStatus.INDEXED
    assert items[0].chunk_count > 0


# ---------------------------------------------------------------------------
# kb_list_items
# ---------------------------------------------------------------------------

def test_list_items_empty(admin_tools):
    """无文档时返回空"""
    result = _find(admin_tools, "kb_list_items").invoke({"limit": 10})
    assert "暂无文档" in result


def test_list_items_after_ingest(admin_tools):
    """导入后应能在列表中看到"""
    _find(admin_tools, "kb_ingest_document").invoke({
        "file_path": "/docs/doc1.md",
        "title": "文档1",
    })
    _find(admin_tools, "kb_ingest_document").invoke({
        "file_path": "/docs/doc2.md",
        "title": "文档2",
    })

    result = _find(admin_tools, "kb_list_items").invoke({"limit": 10})
    assert "共 2 个文档" in result
    assert "文档1" in result
    assert "文档2" in result


def test_list_items_user_denied(user_tools):
    """普通用户不能列出"""
    result = _find(user_tools, "kb_list_items").invoke({"limit": 10})
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# kb_delete_item
# ---------------------------------------------------------------------------

def test_delete_item_success(admin_tools):
    """删除文档成功"""
    created = _find(admin_tools, "kb_ingest_document").invoke({
        "file_path": "/docs/to-delete.md",
        "title": "待删除",
    })
    kb_id = created.split("kb_id: ")[1].split("\n")[0]

    result = _find(admin_tools, "kb_delete_item").invoke({"kb_id": kb_id})
    assert "[文档已删除]" in result
    assert "待删除" in result

    # 验证已删除
    assert _kb_store.get("tenant_A", kb_id) is None


def test_delete_item_nonexistent(admin_tools):
    """删除不存在的文档"""
    result = _find(admin_tools, "kb_delete_item").invoke({"kb_id": "KB-GHOST"})
    assert "[未找到]" in result


def test_delete_item_user_denied(user_tools):
    """普通用户不能删除"""
    result = _find(user_tools, "kb_delete_item").invoke({"kb_id": "KB-X"})
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# kb_rebuild_index
# ---------------------------------------------------------------------------

def test_rebuild_index_success(admin_tools):
    """重建索引"""
    _find(admin_tools, "kb_ingest_document").invoke({
        "file_path": "/docs/doc1.md",
        "title": "doc1",
    })
    _find(admin_tools, "kb_ingest_document").invoke({
        "file_path": "/docs/doc2.md",
        "title": "doc2",
    })

    result = _find(admin_tools, "kb_rebuild_index").invoke({})
    assert "[索引重建完成]" in result
    assert "total_items: 2" in result

    # 验证所有文档状态都是 indexed
    items = _kb_store.list("tenant_A", 10)
    for item in items:
        assert item.status == KBItemStatus.INDEXED
        assert item.indexed_at is not None


def test_rebuild_index_empty(admin_tools):
    """空知识库重建索引"""
    result = _find(admin_tools, "kb_rebuild_index").invoke({})
    assert "[索引重建完成]" in result
    assert "total_items: 0" in result


def test_rebuild_index_user_denied(user_tools):
    """普通用户不能重建索引"""
    result = _find(user_tools, "kb_rebuild_index").invoke({})
    assert "[权限不足]" in result


# ---------------------------------------------------------------------------
# kb_search
# ---------------------------------------------------------------------------

def test_search_user_allowed(user_tools):
    """普通用户可以搜索知识库"""
    result = _find(user_tools, "kb_search").invoke({
        "query": "如何配置 SSO",
        "top_k": 3,
    })
    assert "[搜索结果]" in result
    assert "SSO" in result


def test_search_admin_allowed(admin_tools):
    """admin 也可以搜索"""
    result = _find(admin_tools, "kb_search").invoke({
        "query": "API 文档",
    })
    assert "[搜索结果]" in result


def test_search_returns_multiple_results(user_tools):
    """应返回多个结果"""
    result = _find(user_tools, "kb_search").invoke({
        "query": "测试",
        "top_k": 5,
    })
    # 应至少返回 1 个结果
    assert "相似度" in result


# ---------------------------------------------------------------------------
# 多租户隔离
# ---------------------------------------------------------------------------

def test_cross_tenant_isolation(admin_tools):
    """不同租户的知识库互不可见"""
    _find(admin_tools, "kb_ingest_document").invoke({
        "file_path": "/docs/a-doc.md",
        "title": "tenant-A-doc",
    })

    b_tools = create_kb_tools(
        user_id="admin_B", tenant_id="tenant_B", roles=["admin"],
    )
    result = _find(b_tools, "kb_list_items").invoke({"limit": 10})
    assert "暂无文档" in result
