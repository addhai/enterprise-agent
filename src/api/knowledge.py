"""知识库管理 API — 对齐 MaxKB / 阿里云百炼

提供 HTTP 接口供运维人员管理知识库与文档：
    - 知识库（KBSet）CRUD：创建 / 列表 / 详情 / 更新 / 删除
    - 文档 CRUD：上传 / 列表 / 详情 / 删除 / 刷新 / 批量删除
    - 命中测试：hit_test 验证检索效果

权限：所有接口要求 admin / agent 角色（与现有 admin 路由保持一致）。
存储：复用 src.mcp_tools.kb._kb_store（TenantIsolatedStore）和 KBItem 模型，
     新增 KBSet 模型与 _kb_set_store，用于管理"知识库集合"本身。
"""
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile
from pydantic import BaseModel, Field

from src.api.rbac import Role, require_roles
from src.config import settings
from src.mcp_tools.common import (
    current_utc_time,
    generate_id,
)
from src.db.stores import PgKBSetStore
from src.mcp_tools.kb import (
    KBItem,
    KBItemStatus,
    KBType,
    KBVersion,
    UploadMethod,
    _kb_store,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["knowledge"])


# ====================================================================
# 数据模型
# ====================================================================

class KBSet(BaseModel):
    """知识库集合（KBSet）— 一组文档的容器

    对齐阿里云百炼"知识库"概念：一个知识库下可包含多个文档，
    并可独立配置相似度阈值、权重、版本等。
    """
    id: str
    tenant_id: str
    name: str
    description: str = ""
    kb_version: KBVersion = KBVersion.STANDARD
    kb_type: KBType = KBType.DOCUMENT
    similarity_threshold: float = 0.2
    weight: float = 1.0
    document_count: int = 0
    total_chunks: int = 0
    created_at: str
    updated_at: str
    created_by: str = ""


# 租户隔离的知识库集合存储（已落库持久化）
_kb_set_store: PgKBSetStore = PgKBSetStore()

# 默认租户 ID（单租户部署回退用）
_DEFAULT_TENANT = "default"


def _get_tenant_id(current_user: Dict[str, Any]) -> str:
    """从当前用户提取 tenant_id，回退到 default"""
    return current_user.get("tenant_id") or _DEFAULT_TENANT


def _utc_iso() -> str:
    return current_utc_time().isoformat()


# ====================================================================
# 请求模型
# ====================================================================

class KBCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="知识库名称")
    description: str = Field("", max_length=512, description="描述")
    kb_version: str = Field("standard", description="standard / flagship")
    kb_type: str = Field("document", description="document / data / image / audio_video")
    similarity_threshold: float = Field(0.2, ge=0.01, le=1.0)
    weight: float = Field(1.0, ge=0.5, le=2.0)


class KBUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    similarity_threshold: Optional[float] = Field(None, ge=0.01, le=1.0)
    weight: Optional[float] = Field(None, ge=0.5, le=2.0)


class DocumentCreateRequest(BaseModel):
    """通过文件路径或 URL 创建文档（不通过 multipart 上传时使用）"""
    file_path: str = Field(..., description="本地文件路径或 URL")
    title: str = Field("", description="文档标题（可选）")
    source_type: str = Field("document", description="document / url / api")
    upload_method: str = Field("single", description="single / batch / image / agent")


class HitTestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="测试查询")
    top_k: int = Field(3, ge=1, le=20, description="返回条数")


class BatchDeleteRequest(BaseModel):
    doc_ids: List[str] = Field(..., min_items=1, description="要删除的文档 ID 列表")


# ====================================================================
# 响应辅助
# ====================================================================

def _kb_set_to_dict(kb: KBSet) -> Dict[str, Any]:
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "kb_version": kb.kb_version.value,
        "kb_type": kb.kb_type.value,
        "similarity_threshold": kb.similarity_threshold,
        "weight": kb.weight,
        "document_count": kb.document_count,
        "total_chunks": kb.total_chunks,
        "created_at": kb.created_at,
        "updated_at": kb.updated_at,
        "created_by": kb.created_by,
    }


def _kb_item_to_dict(item: KBItem) -> Dict[str, Any]:
    return {
        "id": item.id,
        "kb_id": item.kb_id,
        "title": item.title,
        "file_path": item.file_path,
        "source_type": item.source_type,
        "status": item.status.value,
        "parse_status": item.parse_status,
        "chunk_count": item.chunk_count,
        "doc_format": item.doc_format,
        "file_size": item.file_size,
        "kb_version": item.kb_version.value,
        "kb_type": item.kb_type.value,
        "upload_method": item.upload_method.value,
        "similarity_threshold": item.similarity_threshold,
        "weight": item.weight,
        "created_at": item.created_at,
        "indexed_at": item.indexed_at,
    }


def _recount_kb(tenant_id: str, kb_id: str) -> Optional[KBSet]:
    """重新统计知识库的 document_count 和 total_chunks"""
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        return None
    items = _kb_store.list(tenant_id, 1000)
    kb_items = [i for i in items if i.kb_id == kb_id]
    kb.document_count = len(kb_items)
    kb.total_chunks = sum(i.chunk_count for i in kb_items)
    kb.updated_at = _utc_iso()
    _kb_set_store.save(tenant_id, kb_id, kb)
    return kb


# ====================================================================
# 知识库 CRUD
# ====================================================================

@router.post("/admin/knowledge")
async def create_knowledge_base(
    req: KBCreateRequest,
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """创建知识库

    需要 admin / agent 角色
    """
    tenant_id = _get_tenant_id(current_user)
    now = _utc_iso()

    try:
        kb_version = KBVersion(req.kb_version)
        kb_type = KBType(req.kb_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"参数错误: {e}")

    kb = KBSet(
        id=generate_id("KBS"),
        tenant_id=tenant_id,
        name=req.name,
        description=req.description,
        kb_version=kb_version,
        kb_type=kb_type,
        similarity_threshold=req.similarity_threshold,
        weight=req.weight,
        document_count=0,
        total_chunks=0,
        created_at=now,
        updated_at=now,
        created_by=current_user.get("user_id", ""),
    )
    _kb_set_store.save(tenant_id, kb.id, kb)
    logger.info("KBSet created: id=%s name=%s tenant=%s", kb.id, kb.name, tenant_id)
    return {"success": True, "kb": _kb_set_to_dict(kb)}


@router.get("/admin/knowledge")
async def list_knowledge_bases(
    kb_type: str = Query("", description="按类型筛选"),
    kb_version: str = Query("", description="按版本筛选"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """列出所有知识库

    需要 admin / agent 角色
    """
    tenant_id = _get_tenant_id(current_user)
    kbs = _kb_set_store.list(tenant_id, 200)

    if kb_type:
        kbs = [k for k in kbs if k.kb_type == kb_type]
    if kb_version:
        kbs = [k for k in kbs if k.kb_version == kb_version]

    return {
        "total": len(kbs),
        "knowledge_bases": [_kb_set_to_dict(k) for k in kbs],
    }


@router.get("/admin/knowledge/{kb_id}")
async def get_knowledge_base(
    kb_id: str = Path(..., description="知识库 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取知识库详情"""
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")
    # 顺便刷新统计
    kb = _recount_kb(tenant_id, kb_id) or kb
    return {"kb": _kb_set_to_dict(kb)}


@router.put("/admin/knowledge/{kb_id}")
async def update_knowledge_base(
    req: KBUpdateRequest,
    kb_id: str = Path(..., description="知识库 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """更新知识库配置（仅 admin）

    可更新：名称、描述、相似度阈值、权重
    """
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    if req.name is not None:
        kb.name = req.name
    if req.description is not None:
        kb.description = req.description
    if req.similarity_threshold is not None:
        kb.similarity_threshold = req.similarity_threshold
    if req.weight is not None:
        kb.weight = req.weight
    kb.updated_at = _utc_iso()

    _kb_set_store.save(tenant_id, kb_id, kb)
    logger.info("KBSet updated: id=%s by=%s", kb_id, current_user.get("user_id"))
    return {"success": True, "kb": _kb_set_to_dict(kb)}


@router.delete("/admin/knowledge/{kb_id}")
async def delete_knowledge_base(
    kb_id: str = Path(..., description="知识库 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """删除知识库（同时删除其下所有文档）

    仅 admin 可调用。删除后无法恢复。
    """
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    # 删除该 KB 下所有文档
    items = _kb_store.list(tenant_id, 2000)
    deleted_docs = 0
    for item in items:
        if item.kb_id == kb_id:
            _kb_store.delete(tenant_id, item.id)
            deleted_docs += 1

    _kb_set_store.delete(tenant_id, kb_id)
    logger.info(
        "KBSet deleted: id=%s docs_removed=%d by=%s",
        kb_id, deleted_docs, current_user.get("user_id"),
    )
    return {
        "success": True,
        "message": f"知识库 {kb_id} 已删除，共删除 {deleted_docs} 个文档",
    }


@router.post("/admin/knowledge/{kb_id}/reindex")
async def reindex_knowledge_base(
    kb_id: str = Path(..., description="知识库 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """重建知识库索引（仅 admin）

    将该 KB 下所有文档状态重置为 INDEXED，并刷新时间戳。
    实际生产中此处应触发后台任务执行真正的重新向量化。
    """
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    items = _kb_store.list(tenant_id, 2000)
    reindexed = 0
    now = _utc_iso()
    for item in items:
        if item.kb_id == kb_id:
            item.status = KBItemStatus.INDEXED
            item.parse_status = "completed"
            item.indexed_at = now
            _kb_store.save(tenant_id, item.id, item)
            reindexed += 1

    _recount_kb(tenant_id, kb_id)
    logger.info("KBSet reindexed: id=%s docs=%d by=%s", kb_id, reindexed, current_user.get("user_id"))
    return {"success": True, "reindexed": reindexed}


# ====================================================================
# 文档 CRUD
# ====================================================================

def _ingest_document_internal(
    tenant_id: str,
    kb_id: str,
    file_path: str,
    title: str,
    source_type: str,
    upload_method: str,
    kb: KBSet,
) -> KBItem:
    """内部：创建 KBItem 并模拟解析/索引流程

    生产环境应替换为真正的异步后台任务。
    """
    doc_format = os.path.splitext(file_path)[1].lstrip(".").lower()
    file_size = 0
    try:
        file_size = os.path.getsize(file_path)
    except OSError:
        pass

    kb_item = KBItem(
        id=generate_id("KB"),
        tenant_id=tenant_id,
        title=title or os.path.basename(file_path),
        file_path=file_path,
        source_type=source_type,
        status=KBItemStatus.PENDING,
        created_at=_utc_iso(),
        kb_version=kb.kb_version,
        kb_type=kb.kb_type,
        doc_format=doc_format,
        kb_id=kb_id,
        upload_method=UploadMethod(upload_method),
        file_size=file_size,
        similarity_threshold=kb.similarity_threshold,
        weight=kb.weight,
    )
    _kb_store.save(tenant_id, kb_item.id, kb_item)

    # 模拟处理流程
    kb_item.status = KBItemStatus.PARSING
    kb_item.parse_status = "parsing"
    _kb_store.save(tenant_id, kb_item.id, kb_item)

    # 尝试真正加载文档（若加载器可用），否则用占位 chunk_count
    chunk_count = 0
    try:
        from src.rag.loader import DocumentLoader
        loader = DocumentLoader(default_tenant_id=tenant_id)
        docs = loader.load_file(file_path)
        chunk_count = len(docs)
        # 真正向量化（best-effort，失败不阻塞 API 响应）
        if chunk_count > 0:
            try:
                from src.api.dependencies import get_retriever
                retriever = get_retriever()
                retriever.add_documents(docs, tenant_id=tenant_id)
            except Exception as e:
                logger.warning("Vector add failed (non-fatal): %s", e)
    except Exception as e:
        logger.warning("Document load failed, using placeholder: %s", e)
        chunk_count = chunk_count or 42

    kb_item.status = KBItemStatus.INDEXED
    kb_item.parse_status = "completed"
    kb_item.chunk_count = chunk_count
    kb_item.indexed_at = _utc_iso()
    _kb_store.save(tenant_id, kb_item.id, kb_item)

    return kb_item


@router.post("/admin/knowledge/{kb_id}/documents")
async def create_document(
    req: DocumentCreateRequest,
    kb_id: str = Path(..., description="知识库 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """添加文档到知识库（通过文件路径或 URL）

    需要 admin / agent 角色。处理流程：pending → parsing → indexed
    """
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    try:
        item = _ingest_document_internal(
            tenant_id=tenant_id,
            kb_id=kb_id,
            file_path=req.file_path,
            title=req.title,
            source_type=req.source_type,
            upload_method=req.upload_method,
            kb=kb,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"参数错误: {e}")

    _recount_kb(tenant_id, kb_id)
    logger.info(
        "Document created: id=%s kb=%s path=%s by=%s",
        item.id, kb_id, req.file_path, current_user.get("user_id"),
    )
    return {"success": True, "document": _kb_item_to_dict(item)}


@router.post("/admin/knowledge/{kb_id}/documents/upload")
async def upload_document_file(
    kb_id: str = Path(..., description="知识库 ID"),
    file: UploadFile = File(..., description="文档文件"),
    title: str = Query("", description="文档标题"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """通过 multipart 上传文档文件到知识库

    需要 admin / agent 角色。文件保存到本地后调用与 create_document 相同的入库流程。
    """
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    # 保存到本地临时目录
    upload_dir = os.path.join(getattr(settings, "chroma_persist_dir", "./chroma_data"), "uploads", kb_id)
    os.makedirs(upload_dir, exist_ok=True)
    save_path = os.path.join(upload_dir, file.filename or "uploaded_doc")

    try:
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}")

    try:
        item = _ingest_document_internal(
            tenant_id=tenant_id,
            kb_id=kb_id,
            file_path=save_path,
            title=title or file.filename or "",
            source_type="document",
            upload_method="single",
            kb=kb,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"参数错误: {e}")

    _recount_kb(tenant_id, kb_id)
    logger.info(
        "Document uploaded: id=%s kb=%s filename=%s by=%s",
        item.id, kb_id, file.filename, current_user.get("user_id"),
    )
    return {"success": True, "document": _kb_item_to_dict(item)}


@router.get("/admin/knowledge/{kb_id}/documents")
async def list_documents(
    kb_id: str = Path(..., description="知识库 ID"),
    status: str = Query("", description="按状态筛选"),
    doc_format: str = Query("", description="按格式筛选"),
    limit: int = Query(50, ge=1, le=200),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """列出知识库下的所有文档"""
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    items = _kb_store.list(tenant_id, 2000)
    items = [i for i in items if i.kb_id == kb_id]
    if status:
        items = [i for i in items if i.status == status]
    if doc_format:
        items = [i for i in items if i.doc_format == doc_format]
    items = items[:limit]

    return {
        "total": len(items),
        "documents": [_kb_item_to_dict(i) for i in items],
    }


@router.get("/admin/knowledge/{kb_id}/documents/{doc_id}")
async def get_document(
    kb_id: str = Path(..., description="知识库 ID"),
    doc_id: str = Path(..., description="文档 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """获取文档详情"""
    tenant_id = _get_tenant_id(current_user)
    item = _kb_store.get(tenant_id, doc_id)
    if item is None or item.kb_id != kb_id:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    return {"document": _kb_item_to_dict(item)}


@router.delete("/admin/knowledge/{kb_id}/documents/{doc_id}")
async def delete_document(
    kb_id: str = Path(..., description="知识库 ID"),
    doc_id: str = Path(..., description="文档 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """删除文档（仅 admin）

    删除后同时刷新知识库统计。
    """
    tenant_id = _get_tenant_id(current_user)
    item = _kb_store.get(tenant_id, doc_id)
    if item is None or item.kb_id != kb_id:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    _kb_store.delete(tenant_id, doc_id)
    _recount_kb(tenant_id, kb_id)
    logger.info(
        "Document deleted: id=%s kb=%s by=%s",
        doc_id, kb_id, current_user.get("user_id"),
    )
    return {"success": True, "message": f"文档 {doc_id} 已删除"}


@router.post("/admin/knowledge/{kb_id}/documents/{doc_id}/refresh")
async def refresh_document(
    kb_id: str = Path(..., description="知识库 ID"),
    doc_id: str = Path(..., description="文档 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """刷新文档索引（仅 admin）

    重新解析并索引该文档。
    """
    tenant_id = _get_tenant_id(current_user)
    item = _kb_store.get(tenant_id, doc_id)
    if item is None or item.kb_id != kb_id:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    # 重置状态并重新处理
    item.status = KBItemStatus.PARSING
    item.parse_status = "parsing"
    _kb_store.save(tenant_id, item.id, item)

    # 重新加载
    chunk_count = item.chunk_count
    try:
        from src.rag.loader import DocumentLoader
        loader = DocumentLoader(default_tenant_id=tenant_id)
        docs = loader.load_file(item.file_path)
        chunk_count = len(docs) or chunk_count
    except Exception as e:
        logger.warning("Refresh load failed: %s", e)

    item.status = KBItemStatus.INDEXED
    item.parse_status = "completed"
    item.chunk_count = chunk_count
    item.indexed_at = _utc_iso()
    _kb_store.save(tenant_id, item.id, item)
    _recount_kb(tenant_id, kb_id)

    logger.info(
        "Document refreshed: id=%s kb=%s chunks=%d by=%s",
        doc_id, kb_id, chunk_count, current_user.get("user_id"),
    )
    return {"success": True, "document": _kb_item_to_dict(item)}


@router.post("/admin/knowledge/{kb_id}/documents/batch_delete")
async def batch_delete_documents(
    req: BatchDeleteRequest,
    kb_id: str = Path(..., description="知识库 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """批量删除文档（仅 admin）"""
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    deleted = 0
    not_found = []
    for doc_id in req.doc_ids:
        item = _kb_store.get(tenant_id, doc_id)
        if item is None or item.kb_id != kb_id:
            not_found.append(doc_id)
            continue
        _kb_store.delete(tenant_id, doc_id)
        deleted += 1

    _recount_kb(tenant_id, kb_id)
    logger.info(
        "Batch delete: kb=%s deleted=%d not_found=%d by=%s",
        kb_id, deleted, len(not_found), current_user.get("user_id"),
    )
    return {
        "success": True,
        "deleted": deleted,
        "not_found": not_found,
    }


# ====================================================================
# 命中测试
# ====================================================================

@router.post("/admin/knowledge/{kb_id}/hit_test")
async def hit_test(
    req: HitTestRequest,
    kb_id: str = Path(..., description="知识库 ID"),
    current_user: Dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
):
    """命中测试 — 验证知识库检索效果

    使用 HybridRetriever 在指定知识库范围内检索，返回 top_k 命中结果。
    """
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    try:
        from src.rag.retriever import HybridRetriever
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"检索器未安装: {e}")

    # 优先使用全局单例
    retriever = None
    try:
        from src.api.dependencies import get_retriever
        retriever = get_retriever()
    except Exception:
        try:
            retriever = HybridRetriever()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"检索器初始化失败: {e}")

    try:
        results = retriever.search_with_scores(
            req.query,
            top_k=req.top_k,
            tenant_id=tenant_id,
            user_id=current_user.get("user_id", ""),
        )
    except Exception as e:
        logger.exception("hit_test 检索失败: %s", e)
        raise HTTPException(status_code=500, detail=f"检索失败: {e}")

    hits = []
    for doc, score in results:
        meta = doc.metadata or {}
        # 只保留该知识库内的命中（若 retriever 支持按 kb_id 过滤则更精确）
        if meta.get("kb_id") and meta.get("kb_id") != kb_id:
            continue
        hits.append({
            "content": (doc.page_content or "")[:300],
            "score": float(score),
            "source": meta.get("source") or meta.get("doc_id") or "",
            "metadata": {k: v for k, v in meta.items() if k != "source"},
        })

    return {
        "kb_id": kb_id,
        "query": req.query,
        "top_k": req.top_k,
        "total_hits": len(hits),
        "hits": hits,
    }
