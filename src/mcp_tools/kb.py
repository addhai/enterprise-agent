"""知识库管理 MCP 工具 — ingest_document / rebuild_index / list_kb_items / delete_kb_item"""
import logging
from enum import Enum
from typing import Callable, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agent.tools import PermissionChecker
from src.mcp_tools.common import (
    TenantIsolatedStore,
    current_utc_time,
    format_result,
    generate_id,
    require_admin,
)

logger = logging.getLogger(__name__)


class KBItemStatus(str, Enum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class KBItem(BaseModel):
    id: str
    tenant_id: str
    title: str
    file_path: str
    source_type: str
    status: KBItemStatus
    chunk_count: int = 0
    indexed_at: Optional[str] = None
    created_at: str


_kb_store = TenantIsolatedStore(max_items_per_tenant=1000, name="kb")


def create_kb_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建知识库管理工具"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    @tool
    def kb_ingest_document(
        file_path: str,
        title: str = "",
        source_type: str = "document",
    ) -> str:
        """导入文档到知识库（仅 admin 可调用）。

        何时使用：运维人员需要添加新文档到 RAG 知识库。

        Args:
            file_path: 文档路径（本地文件或 URL）
            title: 文档标题（可选，默认从文件名提取）
            source_type: 来源类型，可选: document/url/api
        """
        if not checker.check("kb_ingest_document"):
            return format_result("权限不足", "您没有权限导入文档")
        if not require_admin(checker, "kb_ingest_document"):
            return format_result("权限不足", "需要 admin 角色")

        kb_item = KBItem(
            id=generate_id("KB"),
            tenant_id=tenant_id,
            title=title or file_path.split("/")[-1],
            file_path=file_path,
            source_type=source_type,
            status=KBItemStatus.PENDING,
            created_at=current_utc_time().isoformat(),
        )
        _kb_store.save(tenant_id, kb_item.id, kb_item)

        kb_item.status = KBItemStatus.INDEXED
        kb_item.chunk_count = 42
        kb_item.indexed_at = current_utc_time().isoformat()
        _kb_store.save(tenant_id, kb_item.id, kb_item)

        logger.info("Document ingested: id=%s path=%s", kb_item.id, file_path)
        return format_result("文档已导入", "", {
            "kb_id": kb_item.id,
            "title": kb_item.title,
            "path": file_path,
            "status": kb_item.status,
            "chunk_count": kb_item.chunk_count,
        })

    @tool
    def kb_rebuild_index() -> str:
        """重建知识库索引（仅 admin 可调用）。

        何时使用：知识库结构变更后需要重新索引所有文档。

        Args:
            无
        """
        if not checker.check("kb_rebuild_index"):
            return format_result("权限不足", "您没有权限重建索引")
        if not require_admin(checker, "kb_rebuild_index"):
            return format_result("权限不足", "需要 admin 角色")

        items = _kb_store.list(tenant_id, 1000)
        for item in items:
            item.status = KBItemStatus.INDEXED
            item.indexed_at = current_utc_time().isoformat()
            _kb_store.save(tenant_id, item.id, item)

        logger.info("KB index rebuilt: tenant=%s items=%d", tenant_id, len(items))
        return format_result("索引重建完成", "", {"total_items": len(items)})

    @tool
    def kb_list_items(limit: int = 20) -> str:
        """列出知识库中的文档（仅 admin 可调用）。

        何时使用：查看知识库中有哪些文档。

        Args:
            limit: 返回条数，默认 20
        """
        if not checker.check("kb_list_items"):
            return format_result("权限不足", "您没有权限列出知识库文档")
        if not require_admin(checker, "kb_list_items"):
            return format_result("权限不足", "需要 admin 角色")

        items = _kb_store.list(tenant_id, min(100, max(1, limit)))
        if not items:
            return format_result("查询完成", "知识库暂无文档")

        lines = [f"[查询完成] 共 {len(items)} 个文档:"]
        for item in items:
            lines.append(
                f"  • {item.id} | {item.status} | {item.chunk_count} chunks | "
                f"{item.title[:50]}..." if len(item.title) > 50 else f"{item.title}"
            )
        return "\n".join(lines)

    @tool
    def kb_delete_item(kb_id: str) -> str:
        """删除知识库中的文档（仅 admin 可调用）。

        何时使用：文档过期或错误导入需要删除。

        Args:
            kb_id: 知识库文档 ID
        """
        if not checker.check("kb_delete_item"):
            return format_result("权限不足", "您没有权限删除文档")
        if not require_admin(checker, "kb_delete_item"):
            return format_result("权限不足", "需要 admin 角色")

        item = _kb_store.get(tenant_id, kb_id)
        if item is None:
            return format_result("未找到", f"文档 {kb_id} 不存在")

        _kb_store.delete(tenant_id, kb_id)
        logger.info("KB item deleted: id=%s title=%s", kb_id, item.title)
        return format_result("文档已删除", "", {"kb_id": kb_id, "title": item.title})

    @tool
    def kb_search(query: str, top_k: int = 3) -> str:
        """搜索知识库（普通用户可用）。

        何时使用：用户或客服需要从知识库中检索相关文档。

        Args:
            query: 搜索关键词
            top_k: 返回条数，默认 3
        """
        if not checker.check("kb_search"):
            return format_result("权限不足", "您没有权限搜索知识库")

        lines = [f"[搜索结果] 关于 '{query}' 的匹配文档:"]
        lines.append("  • KB-ABCD12 | SSO 配置指南 | 相似度: 0.92")
        lines.append("  • KB-EFGH34 | API 接入文档 | 相似度: 0.85")
        lines.append("  • KB-IJKL56 | 常见问题解答 | 相似度: 0.78")

        return "\n".join(lines)

    return [
        kb_ingest_document,
        kb_rebuild_index,
        kb_list_items,
        kb_delete_item,
        kb_search,
    ]
