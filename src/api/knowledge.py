"""知识库管理 API — 对齐 MaxKB / 阿里云百炼

提供 HTTP 接口供运维人员管理知识库与文档：
    - 知识库（KBSet）CRUD：创建 / 列表 / 详情 / 更新 / 删除
    - 文档 CRUD：上传 / 列表 / 详情 / 删除 / 刷新 / 批量删除
    - 命中测试：hit_test 验证检索效果

权限：所有接口要求 admin / agent 角色（与现有 admin 路由保持一致）。
存储：复用 src.mcp_tools.kb._kb_store（TenantIsolatedStore）和 KBItem 模型，
     新增 KBSet 模型与 _kb_set_store，用于管理"知识库集合"本身。
"""

import contextlib
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile
from pydantic import BaseModel, Field

from src.api.rbac import Role, require_roles
from src.config import settings
from src.db.stores import PgKBSetStore
from src.mcp_tools.common import (
    current_utc_time,
    generate_id,
)
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


class DocumentContentEmptyError(Exception):
    """文档解析后无任何可用内容块。

    归类为客户端可纠正的输入错误（HTTP 400），与向量库/嵌入服务不可用
    这类服务端故障（HTTP 500）区分开，便于调用方决定修正输入还是重试。
    """


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


def _get_tenant_id(current_user: dict[str, Any]) -> str:
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
    kb_type: str = Field(
        "document", description="document / data / image / audio_video"
    )
    similarity_threshold: float = Field(0.2, ge=0.01, le=1.0)
    weight: float = Field(1.0, ge=0.5, le=2.0)


class KBUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=512)
    similarity_threshold: float | None = Field(None, ge=0.01, le=1.0)
    weight: float | None = Field(None, ge=0.5, le=2.0)


class DocumentCreateRequest(BaseModel):
    """通过文件路径 / 网页 URL / 纯文本 创建文档（不通过 multipart 上传时使用）"""

    file_path: str = Field(
        "", description="本地文件路径或网页 URL（document / url 来源）"
    )
    content: str = Field("", description="纯文本内容（source_type=text 时使用）")
    title: str = Field("", description="文档标题（可选）")
    source_type: str = Field("document", description="document / url / text / api")
    upload_method: str = Field("single", description="single / batch / image / agent")


class HitTestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="测试查询")
    top_k: int = Field(3, ge=1, le=20, description="返回条数")


class BatchDeleteRequest(BaseModel):
    doc_ids: list[str] = Field(..., min_items=1, description="要删除的文档 ID 列表")


# ====================================================================
# 响应辅助
# ====================================================================


def _kb_set_to_dict(kb: KBSet) -> dict[str, Any]:
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


def _kb_item_to_dict(item: KBItem) -> dict[str, Any]:
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


def _recount_kb(tenant_id: str, kb_id: str) -> KBSet | None:
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


def _purge_document_vectors(doc_id: str, tenant_id: str) -> None:
    """删除文档在双集合中的全部向量。

    向量层失败时抛 500 且刻意保留业务元数据：元数据一旦先删，残留向量
    就成了无主幽灵，既无法被管理接口追踪也无法再次触发清理。保留元数据
    后运维可凭 doc_id 重试删除，故障可恢复。
    """
    try:
        from src.api.dependencies import get_retriever

        get_retriever().delete_document_vectors(doc_id, tenant_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Vector purge failed: doc_id=%s", doc_id)
        raise HTTPException(
            status_code=500,
            detail=f"向量删除失败，文档元数据已保留，请稍后重试: {e}",
        ) from e


# ====================================================================
# 知识库 CRUD
# ====================================================================


@router.post("/admin/knowledge")
async def create_knowledge_base(
    req: KBCreateRequest,
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
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
        raise HTTPException(status_code=400, detail=f"参数错误: {e}") from e

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
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
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
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
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
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN)),
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
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """删除知识库（同时删除其下所有文档）

    仅 admin 可调用。删除后无法恢复。
    """
    tenant_id = _get_tenant_id(current_user)
    kb = _kb_set_store.get(tenant_id, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    # 删除该 KB 下所有文档：先级联清向量，再删业务元数据。
    # 任一文档向量清理失败即中断并保留现场，由调用方重试，杜绝幽灵向量。
    items = _kb_store.list(tenant_id, 2000)
    deleted_docs = 0
    for item in items:
        if item.kb_id == kb_id:
            _purge_document_vectors(item.id, tenant_id)
            _kb_store.delete(tenant_id, item.id)
            deleted_docs += 1

    _kb_set_store.delete(tenant_id, kb_id)
    logger.info(
        "KBSet deleted: id=%s docs_removed=%d by=%s",
        kb_id,
        deleted_docs,
        current_user.get("user_id"),
    )
    return {
        "success": True,
        "message": f"知识库 {kb_id} 已删除，共删除 {deleted_docs} 个文档",
    }


@router.post("/admin/knowledge/{kb_id}/reindex")
async def reindex_knowledge_base(
    kb_id: str = Path(..., description="知识库 ID"),
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN)),
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
    logger.info(
        "KBSet reindexed: id=%s docs=%d by=%s",
        kb_id,
        reindexed,
        current_user.get("user_id"),
    )
    return {"success": True, "reindexed": reindexed}


# ====================================================================
# 文档 CRUD
# ====================================================================


def _index_document_chunks(
    tenant_id: str,
    kb_id: str,
    doc_id: str,
    source_type: str,
    raw_docs: list[Any],
) -> tuple[int, int]:
    """统一入库管线：元数据盖戳 → HybridChunker 双粒度切分 → 双集合写入。

    所有管理端入库（上传 / URL / 文本 / 刷新）必须走这里，与
    scripts/rebuild_index.py 的离线灌库路径保持同构：
        1. 每个源块注入 kb_id / tenant_id / source_type / doc_id，
           doc_id 是后续级联删除向量的唯一锚点
        2. HybridChunker 产出标准块（512/64）与句子窗口块两种粒度
        3. 标准块写标准集合并重建 BM25，句子块写独立句子集合

    任何一步失败都向上抛异常，由调用方把 KBItem 置为 FAILED。
    返回 (标准块数, 句子块数)。
    """
    if not raw_docs:
        raise DocumentContentEmptyError("文档加载结果为空，无内容可索引")

    for d in raw_docs:
        d.metadata["kb_id"] = kb_id
        if tenant_id and not d.metadata.get("tenant_id"):
            d.metadata["tenant_id"] = tenant_id
        d.metadata["source_type"] = source_type
        d.metadata["doc_id"] = doc_id

    from src.rag.chunker import HybridChunker

    chunker = HybridChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    standard_chunks = chunker.split_standard(raw_docs)
    sentence_chunks = chunker.split_sentences(raw_docs)
    if not standard_chunks:
        raise DocumentContentEmptyError("文档切块结果为空，可能内容过短或格式不受支持")

    from src.api.dependencies import get_retriever

    retriever = get_retriever()
    retriever.add_documents(standard_chunks, tenant_id=tenant_id)
    retriever.index_sentence_chunks(sentence_chunks, tenant_id=tenant_id)

    logger.info(
        "Document indexed: doc_id=%s kb=%s standard_chunks=%d sentence_chunks=%d",
        doc_id,
        kb_id,
        len(standard_chunks),
        len(sentence_chunks),
    )
    return len(standard_chunks), len(sentence_chunks)


def _ingest_document_internal(
    tenant_id: str,
    kb_id: str,
    file_path: str,
    title: str,
    source_type: str,
    upload_method: str,
    kb: KBSet,
    docs: list | None = None,
) -> KBItem:
    """内部：创建 KBItem 并执行真实解析/双粒度索引流程。

    支持三种来源：
        - document：file_path 为本地文件路径（由上传接口落盘）
        - url：file_path 为网页 URL（由调用方预抓取为 docs 传入）
        - text：由调用方将纯文本预加载为 docs 传入

    状态机：pending → parsing → indexed；任一步失败置 failed 并抛 500，
    失败原因写入 parse_status，禁止再用占位 chunk 伪装成功。
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
        with contextlib.suppress(OSError):
            file_size = os.path.getsize(file_path)

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

    kb_item.status = KBItemStatus.PARSING
    kb_item.parse_status = "parsing"
    _kb_store.save(tenant_id, kb_item.id, kb_item)

    try:
        if docs is None:
            from src.rag.loader import DocumentLoader

            loader = DocumentLoader(default_tenant_id=tenant_id)
            docs = loader.load_file(file_path) if file_path else []
        standard_count, _sentence_count = _index_document_chunks(
            tenant_id=tenant_id,
            kb_id=kb_id,
            doc_id=kb_item.id,
            source_type=source_type,
            raw_docs=docs,
        )
    except DocumentContentEmptyError as e:
        # 输入类错误：内容为空或无法解析，调用方应修正文档后重试
        kb_item.status = KBItemStatus.FAILED
        kb_item.parse_status = f"failed: {type(e).__name__}: {e}"[:200]
        kb_item.chunk_count = 0
        _kb_store.save(tenant_id, kb_item.id, kb_item)
        logger.warning(
            "Document ingestion rejected (empty content): doc_id=%s kb=%s: %s",
            kb_item.id,
            kb_id,
            e,
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        # 服务端故障：嵌入/向量库异常等，如实落库失败状态。
        # parse_status 为自由字符串字段，截断到 200 字防止超长异常信息撑爆。
        kb_item.status = KBItemStatus.FAILED
        kb_item.parse_status = f"failed: {type(e).__name__}: {e}"[:200]
        kb_item.chunk_count = 0
        _kb_store.save(tenant_id, kb_item.id, kb_item)
        logger.exception(
            "Document ingestion failed: doc_id=%s kb=%s", kb_item.id, kb_id
        )
        raise HTTPException(status_code=500, detail=f"文档索引失败: {e}") from e

    kb_item.status = KBItemStatus.INDEXED
    kb_item.parse_status = "completed"
    kb_item.chunk_count = standard_count
    kb_item.indexed_at = _utc_iso()
    _kb_store.save(tenant_id, kb_item.id, kb_item)

    return kb_item


@router.post("/admin/knowledge/{kb_id}/documents")
async def create_document(
    req: DocumentCreateRequest,
    kb_id: str = Path(..., description="知识库 ID"),
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
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
            raise HTTPException(
                status_code=400, detail="URL 来源需提供合法的 http(s) 地址"
            )
        try:
            from src.rag.source_ingest import (
                WebIngestDisabledError,
                url_to_documents,
            )

            docs = url_to_documents(req.file_path, req.title, tenant_id)
        except WebIngestDisabledError as e:
            # 内网策略禁用，403 与普通抓取失败的 400 区分，消息可直接展示给管理员
            raise HTTPException(status_code=403, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"网页抓取失败: {e}") from e
    elif source_type == "text":
        if not req.content or not req.content.strip():
            raise HTTPException(status_code=400, detail="文本来源需提供 content 内容")
        try:
            from src.rag.source_ingest import text_to_documents

            docs = text_to_documents(req.content, req.title, tenant_id)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"文本解析失败: {e}") from e
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
        raise HTTPException(status_code=400, detail=f"参数错误: {e}") from e

    _recount_kb(tenant_id, kb_id)
    logger.info(
        "Document created: id=%s kb=%s source=%s by=%s",
        item.id,
        kb_id,
        source_type,
        current_user.get("user_id"),
    )
    return {"success": True, "document": _kb_item_to_dict(item)}


@router.post("/admin/knowledge/{kb_id}/documents/upload")
async def upload_document_file(
    kb_id: str = Path(..., description="知识库 ID"),
    file: UploadFile = File(..., description="文档文件"),
    title: str = Query("", description="文档标题"),
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
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
            "拦截疑似路径穿越的上传: filename=%r resolved=%s",
            file.filename,
            target_path,
        )
        raise HTTPException(status_code=400, detail="文件名非法")

    try:
        # 上传落盘为小型知识文件的一次性写入，阻塞开销可忽略
        with open(target_path, "wb") as f:  # noqa: ASYNC230
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}") from e

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
        raise HTTPException(status_code=400, detail=f"参数错误: {e}") from e

    _recount_kb(tenant_id, kb_id)
    logger.info(
        "Document uploaded: id=%s kb=%s filename=%s by=%s",
        item.id,
        kb_id,
        safe_name,
        current_user.get("user_id"),
    )
    return {"success": True, "document": _kb_item_to_dict(item)}


@router.get("/admin/knowledge/{kb_id}/documents")
async def list_documents(
    kb_id: str = Path(..., description="知识库 ID"),
    status: str = Query("", description="按状态筛选"),
    doc_format: str = Query("", description="按格式筛选"),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
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
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
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
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """删除文档（仅 admin）

    先级联删除双集合中的文档向量，再删业务元数据并刷新知识库统计。
    向量清理失败时返回 500 且保留元数据，可凭原 doc_id 重试。
    """
    tenant_id = _get_tenant_id(current_user)
    item = _kb_store.get(tenant_id, doc_id)
    if item is None or item.kb_id != kb_id:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    _purge_document_vectors(doc_id, tenant_id)
    _kb_store.delete(tenant_id, doc_id)
    _recount_kb(tenant_id, kb_id)
    logger.info(
        "Document deleted: id=%s kb=%s by=%s",
        doc_id,
        kb_id,
        current_user.get("user_id"),
    )
    return {"success": True, "message": f"文档 {doc_id} 已删除"}


@router.post("/admin/knowledge/{kb_id}/documents/{doc_id}/refresh")
async def refresh_document(
    kb_id: str = Path(..., description="知识库 ID"),
    doc_id: str = Path(..., description="文档 ID"),
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN)),
):
    """刷新文档索引（仅 admin）

    真重建流程：重新加载源内容 → 删除该文档旧向量 → 双粒度重新切块入库。
    文本片段来源的原始内容未持久化（file_path 仅为 text:// 占位），
    无法重载，显式返回 400，引导用户删除后重新添加。
    任一步失败置 FAILED 并返回 500，不再假装刷新成功。
    """
    tenant_id = _get_tenant_id(current_user)
    item = _kb_store.get(tenant_id, doc_id)
    if item is None or item.kb_id != kb_id:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    if item.source_type == "text":
        raise HTTPException(
            status_code=400,
            detail="文本片段来源不支持刷新（原始内容未持久化），请删除后重新添加",
        )

    item.status = KBItemStatus.PARSING
    item.parse_status = "parsing"
    _kb_store.save(tenant_id, item.id, item)

    # 异常类必须在 try 外导入：document 分支不执行 url 分支内的导入，
    # 若名字只在分支内绑定，except 求值类型时会抛 UnboundLocalError。
    from src.rag.source_ingest import WebIngestDisabledError

    try:
        # 先重载源内容：加载失败时旧向量原样保留，文档仍可被检索
        if item.source_type == "url":
            from src.rag.source_ingest import url_to_documents

            docs = url_to_documents(item.file_path, item.title, tenant_id)
        else:
            from src.rag.loader import DocumentLoader

            loader = DocumentLoader(default_tenant_id=tenant_id)
            docs = loader.load_file(item.file_path)

        # 再删旧向量。新块同样带 doc_id 戳，若先入库后删除会误删新块，
        # 因此删除必须排在重新入库之前。
        _purge_document_vectors(doc_id, tenant_id)
        chunk_count, _sentence_count = _index_document_chunks(
            tenant_id=tenant_id,
            kb_id=kb_id,
            doc_id=doc_id,
            source_type=item.source_type,
            raw_docs=docs,
        )
    except DocumentContentEmptyError as e:
        item.status = KBItemStatus.FAILED
        item.parse_status = f"failed: {type(e).__name__}: {e}"[:200]
        item.chunk_count = 0
        _kb_store.save(tenant_id, item.id, item)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except WebIngestDisabledError as e:
        # 禁用发生在重载阶段、_purge_document_vectors 之前，旧向量完整保留；
        # 回滚 PARSING 态避免文档卡在解析中，按 403 告知策略原因。
        item.status = KBItemStatus.INDEXED
        item.parse_status = "completed"
        _kb_store.save(tenant_id, item.id, item)
        raise HTTPException(status_code=403, detail=str(e)) from e
    except HTTPException:
        # _purge_document_vectors 的 500 已带保留语义，这里统一落 FAILED 后上抛
        item.status = KBItemStatus.FAILED
        item.parse_status = "failed: refresh aborted, see server logs"
        _kb_store.save(tenant_id, item.id, item)
        raise
    except Exception as e:
        item.status = KBItemStatus.FAILED
        item.parse_status = f"failed: {type(e).__name__}: {e}"[:200]
        item.chunk_count = 0
        _kb_store.save(tenant_id, item.id, item)
        logger.exception("Document refresh failed: doc_id=%s kb=%s", doc_id, kb_id)
        raise HTTPException(status_code=500, detail=f"文档刷新失败: {e}") from e

    item.status = KBItemStatus.INDEXED
    item.parse_status = "completed"
    item.chunk_count = chunk_count
    item.indexed_at = _utc_iso()
    _kb_store.save(tenant_id, item.id, item)
    _recount_kb(tenant_id, kb_id)

    logger.info(
        "Document refreshed: id=%s kb=%s chunks=%d by=%s",
        doc_id,
        kb_id,
        chunk_count,
        current_user.get("user_id"),
    )
    return {"success": True, "document": _kb_item_to_dict(item)}


@router.post("/admin/knowledge/{kb_id}/documents/batch_delete")
async def batch_delete_documents(
    req: BatchDeleteRequest,
    kb_id: str = Path(..., description="知识库 ID"),
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN)),
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
        # 向量先删、元数据后删；向量失败抛 500 中断，已删除的文档
        # 保持已提交状态，失败文档的元数据保留，可凭响应与日志重试。
        _purge_document_vectors(doc_id, tenant_id)
        _kb_store.delete(tenant_id, doc_id)
        deleted += 1

    _recount_kb(tenant_id, kb_id)
    logger.info(
        "Batch delete: kb=%s deleted=%d not_found=%d by=%s",
        kb_id,
        deleted,
        len(not_found),
        current_user.get("user_id"),
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
    current_user: dict[str, Any] = Depends(require_roles(Role.ADMIN, Role.AGENT)),
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
        raise HTTPException(status_code=503, detail=f"检索器未安装: {e}") from e

    # 优先使用全局单例
    retriever = None
    try:
        from src.api.dependencies import get_retriever

        retriever = get_retriever()
    except Exception:
        try:
            retriever = HybridRetriever()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"检索器初始化失败: {e}") from e

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
        raise HTTPException(status_code=500, detail=f"检索失败: {e}") from e

    hits = []
    for doc, score in results:
        meta = doc.metadata or {}
        # 只保留该知识库内的命中（若 retriever 支持按 kb_id 过滤则更精确）
        if meta.get("kb_id") and meta.get("kb_id") != kb_id:
            continue
        hits.append(
            {
                "content": (doc.page_content or "")[:300],
                "score": float(score),
                "source": meta.get("source") or meta.get("doc_id") or "",
                "metadata": {k: v for k, v in meta.items() if k != "source"},
            }
        )

    return {
        "kb_id": kb_id,
        "query": req.query,
        "top_k": req.top_k,
        "total_hits": len(hits),
        "hits": hits,
    }
