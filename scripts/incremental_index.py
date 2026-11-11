#!/usr/bin/env python
"""增量索引同步脚本（2026-11 重写）

监听文档变更，增量更新向量库索引。与 rebuild_index.py 的全量灌库、
knowledge.py 的管理端入库共用同一套契约：
    - HybridChunker 双粒度切分（标准块 + 句子块），分别写两个 collection
    - 每个文件派生确定性 doc_id，变更/删除时按 doc_id 级联清理双集合
    - 经由 HybridRetriever 写入，BM25 内存索引同步重建

旧版三个缺陷已修复：
    1. 删除分支只 pop 本地 JSON、向量残留 → 现调 delete_document_vectors
    2. 更新直接追加、旧块永久残留 → 现按 doc_id 先删后建
    3. 只写标准块、句子集合缺项 → 现双粒度同时写入

使用方式：
    python scripts/incremental_index.py --dir data/docs --once
    python scripts/incremental_index.py --dir data/docs --watch
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.rag.chunker import HybridChunker
from src.rag.loader import DocumentLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# 索引元数据存储路径
INDEX_META_FILE = "chroma_data/index_metadata.json"

# 离线脚本语料统一归 default 租户，与 rebuild_index.py 灌库口径一致
_DEFAULT_TENANT = "default"


def compute_file_hash(file_path: str) -> str:
    """计算文件的 MD5 哈希（仅用于变更检测，非密码学用途）"""
    hasher = hashlib.md5(usedforsecurity=False)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def stable_doc_id(file_path: str) -> str:
    """由绝对路径派生确定性 doc_id。

    增量同步的级联删除锚点：同一路径无论更新多少次，doc_id 恒定，
    旧块才能被 delete_document_vectors 精确清理。加 ``fs-`` 前缀与
    管理端 KB 前缀的 ID 区分来源。
    """
    abspath = str(Path(file_path).resolve())
    # sha1 仅作路径指纹，不承担安全职责
    digest = hashlib.sha1(abspath.encode("utf-8"), usedforsecurity=False).hexdigest()[
        :16
    ]
    return f"fs-{digest}"


def load_index_metadata() -> dict:
    """加载现有索引元数据"""
    if os.path.exists(INDEX_META_FILE):
        with open(INDEX_META_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_index_metadata(meta: dict) -> None:
    """保存索引元数据"""
    os.makedirs(os.path.dirname(INDEX_META_FILE), exist_ok=True)
    meta["updated_at"] = datetime.now().isoformat()
    with open(INDEX_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def find_all_docs(docs_dir: str) -> list:
    """查找目录下所有文档"""
    supported_exts = {".md", ".pdf", ".html", ".htm", ".docx"}
    files = []
    for ext in sorted(supported_exts):
        files.extend(Path(docs_dir).glob(f"**/*{ext}"))
    return sorted(files)


def detect_changes(docs_dir: str, existing_meta: dict) -> dict:
    """检测文档变更

    Returns:
        {"new": [...], "updated": [...], "deleted": [...]}
    """
    current_files = find_all_docs(docs_dir)
    current_hashes = {str(f): compute_file_hash(str(f)) for f in current_files}

    new = []
    updated = []
    deleted = []

    # 新增和更新
    for f in current_files:
        fpath = str(f)
        if fpath not in existing_meta:
            new.append(fpath)
        elif current_hashes[fpath] != existing_meta[fpath].get("hash", ""):
            updated.append(fpath)

    # 删除
    for fpath in existing_meta:
        # 跳过本脚本自己写的簿记字段（updated_at）
        if fpath == "updated_at":
            continue
        if not Path(fpath).exists():
            deleted.append(fpath)

    return {"new": new, "updated": updated, "deleted": deleted}


def _build_retriever():
    """构造与生产依赖注入同构的 HybridRetriever。

    必须显式传 collection_name，sentence_store 才会初始化
    （见 HybridRetriever.__init__ 的句子集合开关条件）。
    """
    from src.rag.retriever import HybridRetriever

    return HybridRetriever(
        persist_directory=settings.chroma_persist_dir,
        collection_name=settings.chroma_collection_name,
    )


def _index_one_file(retriever, chunker, fpath: str) -> tuple[int, int]:
    """加载单个文件并完成双粒度入库，返回 (标准块数, 句子块数)。

    失败直接抛异常，由调用方决定簿记与重试，禁止静默跳过。
    """
    loader = DocumentLoader(enable_dedup=False)
    docs = loader.load_file(fpath)
    if not docs:
        raise RuntimeError("文档加载结果为空")

    doc_id = stable_doc_id(fpath)
    for doc in docs:
        doc.metadata["doc_id"] = doc_id
        doc.metadata["tenant_id"] = _DEFAULT_TENANT
        doc.metadata["source_type"] = "document"
        doc.metadata["source_file"] = str(Path(fpath).resolve())

    standard_chunks = chunker.split_standard(docs, source_file=fpath)
    sentence_chunks = chunker.split_sentences(docs, source_file=fpath)
    if not standard_chunks:
        raise RuntimeError("文档切块结果为空")

    retriever.add_documents(standard_chunks, tenant_id=_DEFAULT_TENANT)
    retriever.index_sentence_chunks(sentence_chunks, tenant_id=_DEFAULT_TENANT)
    return len(standard_chunks), len(sentence_chunks)


def incremental_update(docs_dir: str) -> dict:
    """执行增量索引更新

    Returns:
        各类变更的实际处理计数，供调用方与日志对账。
    """
    chunker = HybridChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        context_window=3,
    )
    retriever = _build_retriever()
    existing_meta = load_index_metadata()

    changes = detect_changes(docs_dir, existing_meta)
    logger.info(
        "Detected changes: new=%d, updated=%d, deleted=%d",
        len(changes["new"]),
        len(changes["updated"]),
        len(changes["deleted"]),
    )

    stats = {"new": 0, "updated": 0, "deleted": 0, "failed": 0}
    if not any(changes.values()):
        logger.info("No changes detected. Index is up to date.")
        return stats

    # 删除优先：先清向量再簿记，失败则保留簿记等待下次重试
    for fpath in changes["deleted"]:
        doc_id = existing_meta.get(fpath, {}).get("doc_id") or stable_doc_id(fpath)
        try:
            result = retriever.delete_document_vectors(doc_id, _DEFAULT_TENANT)
            existing_meta.pop(fpath, None)
            stats["deleted"] += 1
            logger.info(
                "Deleted vectors: %s (standard=%d sentence=%d)",
                Path(fpath).name,
                result["standard_deleted"],
                result["sentence_deleted"],
            )
        except Exception as e:
            stats["failed"] += 1
            logger.error("Failed to delete %s: %s", fpath, e)

    # 新增与更新：更新场景必须先按 doc_id 删旧块，再重新双粒度入库
    for fpath in changes["new"] + changes["updated"]:
        is_update = fpath in changes["updated"]
        doc_id = stable_doc_id(fpath)
        try:
            if is_update:
                retriever.delete_document_vectors(doc_id, _DEFAULT_TENANT)

            std_count, sent_count = _index_one_file(retriever, chunker, fpath)

            # 成功后才更新簿记；失败保留旧记录，下次运行仍能识别为待处理
            existing_meta[fpath] = {
                "hash": compute_file_hash(fpath),
                "doc_id": doc_id,
                "standard_chunks": std_count,
                "sentence_chunks": sent_count,
                "indexed_at": datetime.now().isoformat(),
            }
            stats["updated" if is_update else "new"] += 1
            logger.info(
                "%s: %s (standard=%d sentence=%d)",
                "Updated" if is_update else "Indexed",
                Path(fpath).name,
                std_count,
                sent_count,
            )
        except Exception as e:
            stats["failed"] += 1
            logger.error("Failed to index %s: %s", fpath, e)

    save_index_metadata(existing_meta)
    logger.info(
        "Incremental sync complete: new=%d updated=%d deleted=%d failed=%d",
        stats["new"],
        stats["updated"],
        stats["deleted"],
        stats["failed"],
    )
    return stats


def watch_mode(docs_dir: str, interval: int = 30):
    """监听模式：定期检查文档变更"""
    logger.info("Watching %s for changes (interval=%ds)...", docs_dir, interval)
    last_check = {}

    while True:
        # PERF203：watch 循环必须就地捕获中断与单轮异常，
        # 每轮间隔 30s，try 开销相对磁盘扫描可忽略，无抽取价值
        try:
            files = find_all_docs(docs_dir)
            current = {str(f): os.path.getmtime(str(f)) for f in files}

            if current != last_check:
                logger.info("Change detected, running incremental update...")
                incremental_update(docs_dir)
                last_check = current

            time.sleep(interval)
        except KeyboardInterrupt:  # noqa: PERF203
            logger.info("Stopped watching.")
            break
        except Exception as e:
            logger.error("Watch error: %s", e)
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Incremental RAG Index Sync")
    parser.add_argument("--dir", default="data/docs", help="文档目录")
    parser.add_argument("--once", action="store_true", help="执行一次后退出")
    parser.add_argument("--watch", action="store_true", help="持续监听模式")
    parser.add_argument("--interval", type=int, default=30, help="监听间隔（秒）")
    args = parser.parse_args()

    docs_dir = args.dir
    if not os.path.isdir(docs_dir):
        logger.error("Directory not found: %s", docs_dir)
        sys.exit(1)

    if args.watch:
        watch_mode(docs_dir, args.interval)
    else:
        incremental_update(docs_dir)


if __name__ == "__main__":
    main()
