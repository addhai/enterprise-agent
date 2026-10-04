import sys, os
sys.path.insert(0, r"C:\Users\hai\enterprise-agent")
from src.rag.retriever import HybridRetriever
r = HybridRetriever()
docs = r.search("CloudSync API 分页 limit 最大值 版本控制 v2 下线 410", top_k=3,
                user_id="admin", tenant_id="default",
                user_access_levels=["public", "internal", "confidential", "restricted"])
for d in docs:
    if d.metadata.get("source") == "api_pagination_versioning":
        print("==== FULL CONTENT (len=%d) ====" % len(d.page_content))
        print(d.page_content)
