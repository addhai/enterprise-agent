# -*- coding: utf-8 -*-
"""临时：本地预演 PDF loader 的章节切分与 page 元数据注入。"""
from src.rag.loader import DocumentLoader

loader = DocumentLoader(default_tenant_id="default")
docs = loader.load_file(r"data/docs/thermosense_t90_service_manual.pdf")
print("chapters =", len(docs))
for d in docs:
    m = d.metadata
    print(
        f"page={m.get('page')} total={m.get('total_pages')} "
        f"heading={m.get('heading_text')} len={len(d.page_content)}"
    )
