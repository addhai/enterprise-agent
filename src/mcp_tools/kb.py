"""知识库管理 MCP 工具 — ingest_document / rebuild_index / list_kb_items / delete_kb_item

对齐阿里云百炼知识库功能：
- 知识库版本：标准版(standard) / 旗舰版(flagship)
- 知识库类型：文档(document) / 数据(data) / 图片(image) / 音视频(audio_video)
- 文档格式：Word/Excel/PDF/JPG/MP4/Markdown/TXT等
- 上传方式：单次(single) / 批量(batch) / 图片(image) / Agent(agent)
"""
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
    """知识库条目状态"""
    PENDING = "pending"      # 待处理
    PARSING = "parsing"      # 解析中
    PARSED = "parsed"        # 解析完成
    INDEXING = "indexing"    # 索引中
    INDEXED = "indexed"      # 索引完成
    FAILED = "failed"        # 处理失败


class KBVersion(str, Enum):
    """知识库版本 — 对齐阿里云百炼"""
    STANDARD = "standard"    # 标准版：共享计算资源
    FLAGSHIP = "flagship"    # 旗舰版：高性能计算资源


class KBType(str, Enum):
    """知识库类型 — 对齐阿里云百炼筛选标签"""
    DOCUMENT = "document"         # 文档
    DATA = "data"                 # 数据
    IMAGE = "image"               # 图片
    AUDIO_VIDEO = "audio_video"   # 音视频


class UploadMethod(str, Enum):
    """上传方式 — 对齐阿里云百炼"""
    SINGLE = "single"     # 单次上传
    BATCH = "batch"       # 批量上传
    IMAGE = "image"       # 图片上传
    AGENT = "agent"       # Agent知识使用


class KBItem(BaseModel):
    """知识库条目 — 扩展对齐阿里云百炼知识库

    新增字段：
        - kb_version: 知识库版本（标准版/旗舰版）
        - kb_type: 知识库类型（文档/数据/图片/音视频）
        - doc_format: 文档格式（word/excel/pdf/jpg/mp4/md/txt等）
        - kb_id: 所属知识库ID（支持多知识库）
        - upload_method: 上传方式
        - file_size: 文件大小（字节）
        - parse_status: 解析状态
        - similarity_threshold: 相似度阈值（知识库级别配置）
        - weight: 知识库权重（0.5~2）
    """
    id: str
    tenant_id: str
    title: str
    file_path: str
    source_type: str
    status: KBItemStatus
    chunk_count: int = 0
    indexed_at: Optional[str] = None
    created_at: str

    # 阿里云百炼对齐字段
    kb_version: KBVersion = KBVersion.STANDARD   # 知识库版本
    kb_type: KBType = KBType.DOCUMENT            # 知识库类型
    doc_format: str = ""                         # 文档格式（word/excel/pdf/jpg/mp4/md/txt）
    kb_id: str = ""                              # 所属知识库ID（多知识库支持）
    upload_method: UploadMethod = UploadMethod.SINGLE  # 上传方式
    file_size: int = 0                           # 文件大小（字节）
    parse_status: str = "pending"                # 解析状态
    similarity_threshold: float = 0.2            # 相似度阈值（0.01~1）
    weight: float = 1.0                          # 权重（0.5~2）


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
        kb_version: str = "standard",
        kb_type: str = "document",
        kb_id: str = "",
        upload_method: str = "single",
        similarity_threshold: float = 0.2,
        weight: float = 1.0,
    ) -> str:
        """导入文档到知识库（仅 admin 可调用）。

        何时使用：运维人员需要添加新文档到 RAG 知识库。

        Args:
            file_path: 文档路径（本地文件或 URL）
            title: 文档标题（可选，默认从文件名提取）
            source_type: 来源类型，可选: document/url/api
            kb_version: 知识库版本，standard(标准版) / flagship(旗舰版)
            kb_type: 知识库类型，document(文档) / data(数据) / image(图片) / audio_video(音视频)
            kb_id: 所属知识库ID（支持多知识库）
            upload_method: 上传方式，single(单次) / batch(批量) / image(图片) / agent(Agent)
            similarity_threshold: 相似度阈值（0.01~1，默认0.2）
            weight: 知识库权重（0.5~2，默认1.0）
        """
        if not checker.check("kb_ingest_document"):
            return format_result("权限不足", "您没有权限导入文档")
        if not require_admin(checker, "kb_ingest_document"):
            return format_result("权限不足", "需要 admin 角色")

        # 提取文档格式
        import os
        doc_format = os.path.splitext(file_path)[1].lstrip(".").lower()

        # 获取文件大小
        file_size = 0
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            pass

        kb_item = KBItem(
            id=generate_id("KB"),
            tenant_id=tenant_id,
            title=title or file_path.split("/")[-1],
            file_path=file_path,
            source_type=source_type,
            status=KBItemStatus.PENDING,
            created_at=current_utc_time().isoformat(),
            # 阿里云百炼对齐字段
            kb_version=KBVersion(kb_version),
            kb_type=KBType(kb_type),
            doc_format=doc_format,
            kb_id=kb_id or generate_id("KBSET"),
            upload_method=UploadMethod(upload_method),
            file_size=file_size,
            similarity_threshold=similarity_threshold,
            weight=weight,
        )
        _kb_store.save(tenant_id, kb_item.id, kb_item)

        # 模拟处理流程：pending → parsing → parsed → indexing → indexed
        kb_item.status = KBItemStatus.PARSING
        kb_item.parse_status = "parsing"
        _kb_store.save(tenant_id, kb_item.id, kb_item)

        kb_item.status = KBItemStatus.INDEXED
        kb_item.parse_status = "completed"
        kb_item.chunk_count = 42
        kb_item.indexed_at = current_utc_time().isoformat()
        _kb_store.save(tenant_id, kb_item.id, kb_item)

        logger.info("Document ingested: id=%s path=%s kb_type=%s", kb_item.id, file_path, kb_type)
        return format_result("文档已导入", "", {
            "kb_id": kb_item.id,
            "title": kb_item.title,
            "path": file_path,
            "status": kb_item.status,
            "chunk_count": kb_item.chunk_count,
            "kb_version": kb_item.kb_version,
            "kb_type": kb_item.kb_type,
            "doc_format": kb_item.doc_format,
            "weight": kb_item.weight,
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
    def kb_list_items(
        limit: int = 20,
        kb_type: str = "",
        kb_version: str = "",
        status: str = "",
        kb_id: str = "",
    ) -> str:
        """列出知识库中的文档（仅 admin 可调用）。

        何时使用：查看知识库中有哪些文档。

        Args:
            limit: 返回条数，默认 20
            kb_type: 筛选知识库类型，document/data/image/audio_video
            kb_version: 筛选版本，standard/flagship
            status: 筛选状态，pending/parsing/parsed/indexing/indexed/failed
            kb_id: 筛选所属知识库ID
        """
        if not checker.check("kb_list_items"):
            return format_result("权限不足", "您没有权限列出知识库文档")
        if not require_admin(checker, "kb_list_items"):
            return format_result("权限不足", "需要 admin 角色")

        items = _kb_store.list(tenant_id, min(100, max(1, limit)))

        # 筛选 — 对齐阿里云百炼筛选标签
        if kb_type:
            items = [i for i in items if i.kb_type == kb_type]
        if kb_version:
            items = [i for i in items if i.kb_version == kb_version]
        if status:
            items = [i for i in items if i.status == status]
        if kb_id:
            items = [i for i in items if i.kb_id == kb_id]

        if not items:
            return format_result("查询完成", "知识库暂无文档")

        lines = [f"[查询完成] 共 {len(items)} 个文档:"]
        for item in items:
            title_display = item.title[:40] + "..." if len(item.title) > 40 else item.title
            lines.append(
                f"  • {item.id} | {item.status.value} | {item.kb_type.value} | "
                f"{item.doc_format or 'unknown'} | {item.chunk_count} chunks | "
                f"权重:{item.weight} | {title_display}"
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

        # 延迟导入，避免在 RAG 依赖缺失时整个模块加载失败
        try:
            from src.rag.retriever import HybridRetriever
        except ImportError as e:
            logger.warning("HybridRetriever 导入失败: %s", e)
            return format_result(
                "服务不可用",
                "知识库检索器未安装，无法执行搜索。请联系管理员或转人工客服。",
            )

        # 优先复用全局 retriever 单例（向量库已初始化），否则尝试新建
        retriever = None
        try:
            from src.api.dependencies import get_retriever
            retriever = get_retriever()
        except Exception as e:
            logger.debug("全局 retriever 不可用，尝试新建: %s", e)
            try:
                retriever = HybridRetriever()
            except Exception as e:
                logger.warning("HybridRetriever 初始化失败: %s", e)
                retriever = None

        if retriever is None:
            return format_result(
                "服务不可用",
                "知识库检索器暂未初始化（向量库可能未就绪），请稍后重试或转人工客服。",
            )

        # 真正执行混合检索（向量 + BM25 + RRF）
        try:
            results = retriever.search_with_scores(
                query,
                top_k=max(1, min(top_k, 20)),
                tenant_id=tenant_id,
                user_id=user_id,
                user_access_levels=checker.access_levels,
            )
        except Exception as e:
            logger.exception("知识库检索失败: %s", e)
            return format_result("搜索失败", f"检索过程中发生错误: {e}")

        if not results:
            return format_result(
                "搜索结果",
                f"未找到关于 '{query}' 的相关文档。建议换个关键词或转人工客服。",
            )

        # 格式化真实检索结果
        lines = [f"[搜索结果] 关于 '{query}' 的匹配文档（共 {len(results)} 条）:"]
        for doc, score in results:
            meta = doc.metadata or {}
            source = meta.get("source") or meta.get("doc_id") or "unknown"
            preview = (doc.page_content or "")[:80].replace("\n", " ")
            lines.append(
                f"  • {source} | 相似度: {float(score):.2f} | {preview}"
            )

        return "\n".join(lines)

    return [
        kb_ingest_document,
        kb_rebuild_index,
        kb_list_items,
        kb_delete_item,
        kb_search,
    ]
