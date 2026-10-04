import sys, os
sys.path.insert(0, r"C:\Users\hai\enterprise-agent")
from src.rag.retriever import HybridRetriever

# 应用里 WS 会话实际用的自然语言 query
QUERY = ("CloudSync API 的分页接口，单次请求 limit 参数最大能设多少？"
         "v2 版本的分页接口什么时候下线，下线后返回什么 HTTP 状态码？")

r = HybridRetriever()
docs = r.search(QUERY, top_k=3, user_id="admin", tenant_id="default",
                user_access_levels=["public", "internal", "confidential", "restricted"])
print(f"[RESULT] retriever.search (natural query) returned {len(docs)} docs")
for i, d in enumerate(docs, 1):
    print(f"\n##### DOC {i} source={d.metadata.get('source')} tenant={d.metadata.get('tenant_id')} acl={d.metadata.get('access_level')}")
    print(d.page_content)
