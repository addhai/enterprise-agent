# -*- coding: utf-8 -*-
"""临时：核验生产向量库中新 PDF 切片的 page 元数据。"""
import chromadb

client = chromadb.PersistentClient(path="/app/chroma_data")
col = client.get_collection("knowledge_base")
result = col.get(
    where={"source": "thermosense_t90_service_manual.pdf"},
    include=["metadatas"],
)
print("块数:", len(result["ids"]))
pages = []
for i, (cid, meta) in enumerate(zip(result["ids"], result["metadatas"])):
    page = meta.get("page", "<键不存在>")
    pages.append(page)
    print(
        f"  块{i}: id={cid[:20]} page={page} "
        f"heading={meta.get('heading_text')} keys={sorted(meta.keys())}"
    )
non_null = [p for p in pages if isinstance(p, int)]
print(f"page 非空整数块数: {len(non_null)} / {len(pages)}; pages={sorted(non_null)}")
