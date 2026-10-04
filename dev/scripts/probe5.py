"""验证 top_k=5 后，自然问法能否召回到包含答案事实的 chunk"""
import sys, os
sys.path.insert(0, r"C:\Users\hai\enterprise-agent")
os.chdir(r"C:\Users\hai\enterprise-agent")

from src.rag.retriever import HybridRetriever

r = HybridRetriever()

# 每个问题配一组「只有文档里才有」的证伪关键词
cases = [
    ("CloudSync v2 版本什么时候下线 返回什么状态码", ["410", "2025-12-31"]),
    ("CloudSync API 分页 limit 参数最大能填多少", ["100"]),
    ("CloudSync 分页游标有效期多久", ["游标", "小时"]),
]

for q, must_have in cases:
    print("\n" + "=" * 70)
    print("QUERY:", q)
    docs = r.search(q, top_k=5,
                    user_id="admin", tenant_id="default",
                    user_access_levels=["public", "internal", "confidential", "restricted"])
    # 模拟工具层：截断 1200 后拼接，这才是 LLM 真正看到的上下文
    ctx = "\n\n---\n\n".join(
        f"[Doc {i} - {d.metadata.get('source')}]\n{d.page_content[:1200]}"
        for i, d in enumerate(docs, 1)
    )
    hit = [kw for kw in must_have if kw in ctx]
    miss = [kw for kw in must_have if kw not in ctx]
    print(f"-> {len(docs)} chunks | sources={[d.metadata.get('source') for d in docs]}")
    print(f"-> 命中关键事实: {hit}  缺失: {miss}")
    print("-> 结论:", "PASS 答案事实已进上下文" if not miss else "FAIL 事实未进上下文")
