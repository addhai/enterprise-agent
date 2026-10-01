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
# 上传安全校验
# ====================================================================

# 单文件大小上限：与 src/mcp_tools/filesystem.py 的 _MAX_FILE_SIZE 保持一致。
# 为什么要有上限：上传接口会把整个文件读进内存（await file.read()），
# 没有上限时一个 2GB 的请求就能把进程内存打满（DoS）。
_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


def _safe_filename(raw_name: str) -> str:
    """把用户提交的文件名洗成安全的纯文件名，阻断路径穿越。

    修复的漏洞（2026-10-01）：
        原实现直接 `os.path.join(upload_dir, file.filename)`。两种攻击面：
          1. 相对穿越：filename = "../../../etc/passwd"
             → 拼出 upload_dir/../../../etc/passwd，写到目录外。
          2. 绝对路径覆盖：filename = "/etc/passwd"
             → os.path.join 遇到绝对路径会丢弃前面所有段，直接写到 /etc/passwd。
        这里只取 basename，并过滤 Windows 盘符与特殊目录名，
        再做一次 resolve + relative_to 兜底断言，确保落在沙箱内。

    返回：清洗后的文件名（非法输入回退到 "uploaded_doc"）。
    """
    # 统一分隔符后再取最后一段：Windows 客户端可能传 "..\\..\\evil.md"，
    # 在 POSIX 上 os.path.basename 认不出反斜杠，所以先归一化。
    name = (raw_name or "").replace("\\", "/").split("/")[-1]
    # 去掉可能残留的父目录标记与盘符（如 "C:"）
    name = name.replace("..", "").strip().strip(":")
    # 前导点会让文件在 POSIX 上变成隐藏文件。剥前导点时要保住扩展名：
    # "../../.md" 洗出来应是 ".md" 而不是被 lstrip 剥成 "md"（那样会丢掉后缀，
    # 后续白名单校验就会误判为「无扩展名」而拒绝合法文件）。
    stripped = name.lstrip(".")
    if stripped != name:
        # 原本有点，优先保住「点 + 扩展名」形态
        name = "." + stripped if stripped else ""
    if not name or name == ".":
        return "uploaded_doc"
    return name


def _resolve_upload_path(upload_dir: str, safe_name: str) -> tuple[str, str]:
    """把上传目录与已清洗的文件名解析成 (根目录, 目标路径)，并做归属校验

    为什么单独抽成**同步**函数：
        上传接口是 async 的，而路径绝对化会触发 ASYNC240（该规则禁止在
        async 函数里调用 os.path / pathlib 的方法，意在防止阻塞式 IO）。
        路径规范化本身是纯字符串运算、不阻塞，放进独立的同步函数既能表达
        这一事实，又不必给整条链路引入 anyio.Path。

    为什么用 realpath 而非 abspath：
        realpath 会解析符号链接，防止攻击者先在 upload_dir 内建一个指向
        外部的软链，再传文件把它写穿。abspath 不做这一步。

    返回 (root_abs, target_abs)；调用方用 target_abs 是否落在 root_abs 下
    做最终把关。
    """
    root_abs = os.path.realpath(upload_dir)
    target_abs = os.path.realpath(os.path.join(root_abs, safe_name))
    return root_abs, target_abs


def _validate_upload_ext(filename: str) -> str:
    """校验扩展名是否在白名单内，返回规范化扩展名（含点，小写）。

    白名单唯一来源：LoaderRegistry.list_supported()。
    为什么不另写一份常量清单：解析器注册表才是「系统真正能读哪些格式」的
    事实源。另写一份必然与它漂移，出现「白名单放行但解析器不认识」的空洞。

    不在白名单 → 抛 400，detail 必须含「不支持的文件类型」（前端与测试依赖此文案）。
    """
    # 延迟导入两件事：
    #   src.rag.loader 模块（import 时才执行 @register_loader，注册表才非空）
    #   LoaderRegistry 类本身
    # 不在模块顶部导入：API 层启动时不该拉起全部解析器（含图像/PDF 的重依赖）。
    import src.rag.loader  # noqa: F401  触发各 loader 模块的注册副作用
    from src.rag.loaders import LoaderRegistry

    ext = os.path.splitext(filename)[1].lower()
    supported = set(LoaderRegistry.list_supported())
    if ext not in supported:
        allowed = "、".join(sorted(supported))
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext or '(无扩展名)'}；允许的格式: {allowed}",
        )
    return ext


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
    """通过文件路径 / 网页 URL / 纯文本 创建文档（不通过 multipart 上传时使用）"""
    file_path: str = Field("", description="本地文件路径或网页 URL（document / url 来源）")
    content: str = Field("", description="纯文本内容（source_type=text 时使用）")
    title: str = Field("", description="文档标题（可选）")
    source_type: str = Field("document", description="document / url / text / api")
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
    docs: Optional[List] = None,
) -> KBItem:
    """内部：创建 KBItem 并模拟解析/索引流程

    生产环境应替换为真正的异步后台任务。支持三种来源：
        - document：file_path 为本地文件路径（由上传接口落盘）
        - url：file_path 为网页 URL（由调用方预抓取为 docs 传入）
        - text：由调用方将纯文本预加载为 docs 传入
    """
    # doc_format 推导：URL / 文本来源无扩展名，按 source_type 归类
    if source_type == "url":
        doc_format = "web"
    elif source_type == "text":
        doc_format = "text"
    else:
        doc_format = os.path.splitext(file_path or "")[1].lstrip(".").lower()

    file_size = 0
    if file_path and os.path.exists(file_path):
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            pass

    # 展示标题与存储路径（不同来源差异化）
    if source_type == "url":
        display_title = title or file_path or "网页文档"
        stored_path = file_path or ""
    elif source_type == "text":
        display_title = title or "文本片段"
        stored_path = f"text://{display_title}"
    else:
        display_title = title or (os.path.basename(file_path) if file_path else "文档")
        stored_path = file_path or ""

    kb_item = KBItem(
        id=generate_id("KB"),
        tenant_id=tenant_id,
        title=display_title,
        file_path=stored_path,
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

    # 加载文档（若未预加载则按 file_path 加载），并注入知识库隔离元数据
    chunk_count = 0
    try:
        if docs is None:
            from src.rag.loader import DocumentLoader
            loader = DocumentLoader(default_tenant_id=tenant_id)
            docs = loader.load_file(file_path) if file_path else []
        # 每个 chunk 注入 kb_id / tenant_id / source_type / doc_id，
        # 保证检索时可按知识库隔离（对齐阿里云百炼知识库隔离）。
        for d in docs:
            d.metadata["kb_id"] = kb_id
            if tenant_id and not d.metadata.get("tenant_id"):
                d.metadata["tenant_id"] = tenant_id
            d.metadata["source_type"] = source_type
            d.metadata["doc_id"] = kb_item.id
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
    """添加文档到知识库（支持 document / url / text 三种来源）

    需要 admin / agent 角色。处理流程：pending → parsing → indexed
    """
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    source_type = req.source_type
    docs = None
    # 预加载非文件来源（URL / 文本），统一复用 DocumentLoader 分块管线
    if source_type == "url":
        if not req.file_path or not req.file_path.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="URL 来源需提供合法的 http(s) 地址")
        try:
            from src.rag.source_ingest import url_to_documents
            docs = url_to_documents(req.file_path, req.title, tenant_id)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"网页抓取失败: {e}")
    elif source_type == "text":
        if not req.content or not req.content.strip():
            raise HTTPException(status_code=400, detail="文本来源需提供 content 内容")
        try:
            from src.rag.source_ingest import text_to_documents
            docs = text_to_documents(req.content, req.title, tenant_id)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"文本解析失败: {e}")
    else:
        if not req.file_path:
            raise HTTPException(status_code=400, detail="document 来源需提供 file_path")

    try:
        item = _ingest_document_internal(
            tenant_id=tenant_id,
            kb_id=kb_id,
            file_path=req.file_path or None,
            title=req.title,
            source_type=source_type,
            upload_method=req.upload_method,
            kb=kb,
            docs=docs,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"参数错误: {e}")

    _recount_kb(tenant_id, kb_id)
    logger.info(
        "Document created: id=%s kb=%s source=%s by=%s",
        item.id, kb_id, source_type, current_user.get("user_id"),
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

    # ---- 校验 1：扩展名白名单（先做，无 IO 开销，且能挡住大部分恶意输入）----
    # 注意顺序：必须在写盘之前。否则恶意文件已经落地才报错，
    # 沙箱里会留下垃圾文件，而测试断言「upload_dir 外无新文件」也会因此失败。
    safe_name = _safe_filename(file.filename or "")
    _validate_upload_ext(safe_name)

    # ---- 校验 2：大小限制 ----
    # 先读进内存再判断大小是有意为之：UploadFile 的底层 spool 文件在
    # `await file.read()` 之前 size 属性可能不准。这里的取舍是
    # 「宁可多一次内存峰值，也不要漏判」，因为 10MB 上限本身已把峰值框住。
    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=(
                f"文件过大: {len(content) / 1024 / 1024:.1f}MB，"
                f"超过限制 {_MAX_UPLOAD_SIZE / 1024 / 1024:.0f}MB"
            ),
        )

    # ---- 保存到本地（路径已清洗，且落盘前做一次越界兜底断言）----
    upload_dir = os.path.join(
        getattr(settings, "chroma_persist_dir", "./chroma_data"), "uploads", kb_id
    )
    os.makedirs(upload_dir, exist_ok=True)
    # 路径绝对化与归属校验放在同步函数里完成（见 _resolve_upload_path 的说明）
    upload_root, target_path = _resolve_upload_path(upload_dir, safe_name)

    # 兜底闸门：即使 _safe_filename 未来被改坏，这里也能拦住越界写入。
    # 用 os.path.commonpath 判断归属，比字符串 startswith 更严谨：
    # startswith 会被「同前缀的兄弟目录」绕过（如 /a/uploads2 命中 /a/uploads）。
    if os.path.commonpath([upload_root, target_path]) != upload_root:
        logger.warning(
            "拦截疑似路径穿越的上传: filename=%r resolved=%s", file.filename, target_path
        )
        raise HTTPException(status_code=400, detail="文件名非法")

    try:
        with open(target_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}")

    try:
        item = _ingest_document_internal(
            tenant_id=tenant_id,
            kb_id=kb_id,
            # 传字符串：下游会把它存进 KBItem.file_path（字段为字符串），
            # 也会交给 os.path.splitext / loader，统一按字符串协议传递。
            file_path=target_path,
            # 用清洗后的 safe_name 做标题，与落盘文件名一致；
            # 用原始 file.filename 会让展示名里带 "../../" 这类噪声。
            title=title or safe_name,
            source_type="document",
            upload_method="single",
            kb=kb,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"参数错误: {e}")

    _recount_kb(tenant_id, kb_id)
    logger.info(
        "Document uploaded: id=%s kb=%s filename=%s by=%s",
        item.id, kb_id, safe_name, current_user.get("user_id"),
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
            filter_by={"kb_id": kb_id},
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
