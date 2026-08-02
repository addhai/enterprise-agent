"""Repository 支撑的内存接口兼容 Store（替代 TenantIsolatedStore）

- PgKBSetStore：替代 knowledge.py 的 _kb_set_store，返回 knowledge.KBSet 对象
- PgKBItemStore：替代 mcp_tools.kb 的 _kb_store，返回 mcp_tools.kb.KBItem 对象

接口与 TenantIsolatedStore 的 get/list/save/delete 保持一致，
因此 knowledge.py / mcp_tools/kb.py 的调用点几乎无需改动。
底层落库到 knowledge_bases / kb_documents 表（Postgres / SQLite 自动切换）。
"""
from __future__ import annotations

from typing import Any, List, Optional

from src.db.repositories import (
    kb_item_delete,
    kb_item_get,
    kb_item_list,
    kb_item_save,
    kb_set_delete,
    kb_set_get,
    kb_set_list,
    kb_set_save,
)


class PgKBSetStore:
    """知识库集合存储（KBSet）— 落库版本"""

    def get(self, tenant_id: str, kb_id: str) -> Optional[Any]:
        return kb_set_get(tenant_id, kb_id)

    def list(self, tenant_id: str, limit: int = 200) -> List[Any]:
        return kb_set_list(tenant_id)

    def save(self, tenant_id: str, kb_id: str, kb: Any) -> Any:
        return kb_set_save(kb)

    def delete(self, tenant_id: str, kb_id: str) -> bool:
        return kb_set_delete(tenant_id, kb_id)

    def reset(self) -> None:
        from src.db.repositories import kb_set_reset
        kb_set_reset()


class PgKBItemStore:
    """知识库文档存储（KBItem）— 落库版本"""

    def get(self, tenant_id: str, item_id: str) -> Optional[Any]:
        return kb_item_get(tenant_id, item_id)

    def list(self, tenant_id: str, limit: int = 1000) -> List[Any]:
        return kb_item_list(tenant_id, limit)

    def save(self, tenant_id: str, item_id: str, item: Any) -> Any:
        return kb_item_save(item)

    def delete(self, tenant_id: str, item_id: str) -> bool:
        return kb_item_delete(tenant_id, item_id)

    def reset(self) -> None:
        from src.db.repositories import kb_item_reset
        kb_item_reset()
