#!/usr/bin/env python
"""知识库全量重建（幂等）：无条件清空标准/句子两个 Chroma collection 后重建。

与 ingest_docs.py 的区别：
- ingest_docs.py 只增不删，文件已从磁盘移除的「幽灵向量」会永久残留；
- 本脚本先 delete_collection 再灌入，重复执行结果一致，是归档/删除语料后的
  正式重建入口。生产在容器内执行：
      python scripts/rebuild_index.py --yes
  重建完成后建议 restart app，刷新进程内持有的 Chroma collection 句柄。

仅支持 Chroma 后端（生产固定 VECTOR_STORE_BACKEND=chroma）。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.rag.chunker import HybridChunker
from src.rag.loader import DocumentLoader
from src.rag.vector_store import VectorStoreManager


def _source_distribution(manager: VectorStoreManager) -> dict:
    """统计 collection 内各 source 文件的 chunk 数，用于重建前后对账"""
    coll = manager.store._collection
    data = coll.get(include=["metadatas"])
    dist: dict = {}
    for meta in data.get("metadatas") or []:
        source = (meta or {}).get("source", "?")
        dist[source] = dist.get(source, 0) + 1
    return dict(sorted(dist.items(), key=lambda kv: -kv[1]))


def _reset_collection(persist_dir: str, name: str) -> VectorStoreManager:
    """drop 旧 collection 并返回一个绑定全新空 collection 的 manager"""
    old = VectorStoreManager(persist_directory=persist_dir, collection_name=name)
    before = old.count()
    print(f"  [{name}] drop 前 chunk 数: {before}")
    old.delete_collection()
    # delete_collection 后旧实例句柄已失效，必须重新实例化拿新集合
    return VectorStoreManager(persist_directory=persist_dir, collection_name=name)


def main() -> int:
    parser = argparse.ArgumentParser(description="全量重建 Chroma 知识库索引")
    parser.add_argument(
        "--docs-dir",
        default=str(Path(__file__).parent.parent / "data" / "docs"),
        help="语料目录（默认 data/docs）",
    )
    parser.add_argument(
        "--persist-dir",
        default=None,
        help="Chroma 持久化目录（默认取 settings.chroma_persist_dir）",
    )
    parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir).resolve()
    persist_dir = args.persist_dir or settings.chroma_persist_dir
    base_name = settings.chroma_collection_name
    sentence_name = f"{base_name}_sentences"

    print("=" * 60)
    print("知识库全量重建")
    print(f"  语料目录:   {docs_dir}")
    print(f"  Chroma 目录: {persist_dir}")
    print(f"  collections: {base_name} / {sentence_name}")
    print("=" * 60)

    if not args.yes:
        ans = input("将无条件清空上述两个 collection，输入 yes 继续: ").strip().lower()
        if ans != "yes":
            print("已取消")
            return 1

    # 1. 加载 + 切块（先于 drop，加载失败时旧索引不受影响）
    print("\n[1/4] 加载并切分语料...")
    loader = DocumentLoader(enable_dedup=True)
    documents = loader.load_directory(str(docs_dir))
    if not documents:
        print("错误：未加载到任何文档，为保护线上索引中止重建")
        return 2
    sources = sorted({d.metadata.get("source", "?") for d in documents})
    print(f"  文档块: {len(documents)}，来源文件 {len(sources)} 个:")
    for s in sources:
        print(f"    - {s}")

    chunker = HybridChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        context_window=3,
    )
    standard_chunks = chunker.split_standard(documents)
    sentence_chunks = chunker.split_sentences(documents)
    print(f"  标准块: {len(standard_chunks)} / 句子块: {len(sentence_chunks)}")

    # 2. 清空两个 collection
    print("\n[2/4] 清空旧 collection...")
    std_store = _reset_collection(persist_dir, base_name)
    sent_store = _reset_collection(persist_dir, sentence_name)

    # 3. 灌入
    print("\n[3/4] 写入向量（本地 CPU embedding，耗时取决于语料规模）...")
    std_store.add_documents(standard_chunks)
    sent_store.add_documents(sentence_chunks)

    # 4. 对账
    print("\n[4/4] 重建后对账:")
    std_dist = _source_distribution(std_store)
    sent_count = sent_store.count()
    print(f"  {base_name}: {std_store.count()} chunks")
    for source, n in std_dist.items():
        print(f"    {n:4d}  {source}")
    print(f"  {sentence_name}: {sent_count} chunks")

    if std_store.count() == 0 or sent_count == 0:
        print("错误：重建后集合为空，索引异常")
        return 3

    print("\n完成。请重启应用进程以刷新 Chroma 句柄。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
