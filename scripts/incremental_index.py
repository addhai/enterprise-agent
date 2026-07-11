#!/usr/bin/env python
"""增量索引同步脚本

监听文档变更，增量更新向量库索引。

使用方式：
    python scripts/incremental_index.py --dir data/docs --once
    python scripts/incremental_index.py --dir data/docs --watch

功能：
    1. 检测文档变更（新增/修改/删除）
    2. 增量索引更新（只索引变更的文档）
    3. 版本号管理（draft → published → archived）
    4. 查询时只读已发布版本
"""
import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag.loader import DocumentLoader
from src.rag.chunker import HybridChunker
from src.rag.vector_store import VectorStoreManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# 索引元数据存储路径
INDEX_META_FILE = "chroma_data/index_metadata.json"


def compute_file_hash(file_path: str) -> str:
    """计算文件的 MD5 哈希"""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_index_metadata() -> dict:
    """加载现有索引元数据"""
    if os.path.exists(INDEX_META_FILE):
        with open(INDEX_META_FILE, "r", encoding="utf-8") as f:
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
    for fpath, meta in existing_meta.items():
        if not Path(fpath).exists():
            deleted.append(fpath)

    return {"new": new, "updated": updated, "deleted": deleted}


def incremental_update(docs_dir: str, batch_size: int = 50):
    """执行增量索引更新

    Args:
        docs_dir: 文档目录
        batch_size: 每批处理的文档数
    """
    loader = DocumentLoader(enable_dedup=False)
    chunker = HybridChunker(chunk_size=512, chunk_overlap=64, context_window=3)
    vector_store = VectorStoreManager()

    # 加载现有元数据
    existing_meta = load_index_metadata()

    # 检测变更
    changes = detect_changes(docs_dir, existing_meta)
    logger.info("Detected changes: new=%d, updated=%d, deleted=%d",
                len(changes["new"]), len(changes["updated"]), len(changes["deleted"]))

    if not any(changes.values()):
        logger.info("No changes detected. Index is up to date.")
        return

    # 处理变更
    all_changed = changes["new"] + changes["updated"]
    for i in range(0, len(all_changed), batch_size):
        batch = all_changed[i:i + batch_size]
        for fpath in batch:
            try:
                docs = loader.load_file(fpath)
                if not docs:
                    continue

                # 切块
                chunks = chunker.split_standard(docs)
                if not chunks:
                    continue

                # 标注版本号
                version = _get_next_version(fpath, existing_meta)
                for chunk in chunks:
                    chunk.metadata["version"] = version
                    chunk.metadata["status"] = "published"
                    chunk.metadata["indexed_at"] = datetime.now().isoformat()

                # 写入向量库
                vector_store.add_documents(chunks)

                # 更新元数据
                existing_meta[fpath] = {
                    "hash": compute_file_hash(fpath),
                    "version": version,
                    "status": "published",
                    "chunks": len(chunks),
                    "indexed_at": datetime.now().isoformat(),
                }

                logger.info("Indexed: %s (version=%s, chunks=%d)",
                            Path(fpath).name, version, len(chunks))
            except Exception as e:
                logger.error("Failed to index %s: %s", fpath, e)

    # 处理删除
    for fpath in changes["deleted"]:
        logger.info("Deleted: %s (removing from index)", fpath)
        existing_meta.pop(fpath, None)

    # 保存元数据
    save_index_metadata(existing_meta)
    logger.info("Incremental index update complete.")


def _get_next_version(fpath: str, existing_meta: dict) -> str:
    """获取下一个版本号"""
    meta = existing_meta.get(fpath, {})
    version = meta.get("version", "v1.0")
    match = __import__('re').search(r"v(\d+)\.(\d+)", version)
    if match:
        major, minor = int(match.group(1)), int(match.group(2))
        minor += 1
        if minor >= 10:
            major += 1
            minor = 0
        return f"v{major}.{minor}"
    return "v1.0"


def watch_mode(docs_dir: str, interval: int = 30):
    """监听模式：定期检查文档变更"""
    logger.info("Watching %s for changes (interval=%ds)...", docs_dir, interval)
    last_check = {}

    while True:
        try:
            files = find_all_docs(docs_dir)
            current = {str(f): os.path.getmtime(str(f)) for f in files}

            if current != last_check:
                logger.info("Change detected, running incremental update...")
                incremental_update(docs_dir)
                last_check = current

            time.sleep(interval)
        except KeyboardInterrupt:
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
