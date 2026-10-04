import sys, os
sys.path.insert(0, r"C:\Users\hai\enterprise-agent")
os.chdir(r"C:\Users\hai\enterprise-agent")

from src.rag.retriever import HybridRetriever

r = HybridRetriever()

queries = [
    "CloudSync API 分页 limit 最大值是多少",
    "CloudSync v2 版本什么时候下线 返回什么状态码",
    "CloudSync API 版本控制 怎么用",
]

for q in queries:
    print("\n" + "=" * 70)
    print("QUERY:", q)
    docs = r.search(q, top_k=3,
                    user_id="admin", tenant_id="default",
                    user_access_levels=["public", "internal", "confidential", "restricted"])
    print(f"-> returned {len(docs)} chunks")
    for i, d in enumerate(docs, 1):
        c = d.page_content
        flags = []
        for kw in ["410", "Gone", "limit", "100", "版本", "v2", "下线", "分页"]:
            if kw.lower() in c.lower():
                flags.append(kw)
        print(f"\n--- chunk {i} | source={d.metadata.get('source')} | chunk_index={d.metadata.get('chunk_index')} | flags={flags}")
        print(c[:900])
