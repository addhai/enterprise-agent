# -*- coding: utf-8 -*-
"""容器内复现：真实 retriever + create_agent，检查知识库工具是否返回文档内容"""
import sys
sys.path.insert(0, "/app")

from src.api.dependencies import get_retriever
from src.agent.agent import CustomerServiceAgent

retriever = get_retriever()

# 直接验证检索器
docs = retriever.search("T100 测温范围", top_k=3, user_id="u1", tenant_id="default")
sys.stderr.write("DIRECT RETRIEVER: %d docs\n" % len(docs))
for d in docs[:2]:
    sys.stderr.write("  - %s: %s\n" % (d.metadata.get("source"), d.page_content[:60].replace("\n", " ")))

agent = CustomerServiceAgent(
    retriever=retriever,
    user_id="u1",
    tenant_id="default",
    max_turns=3,
)
r = agent.run_with_trace("T100 测温范围是多少？", chat_history=[])
sys.stderr.write("=== agent messages ===\n")
for m in r.get("messages", []):
    kind = type(m).__name__
    tc = getattr(m, "tool_calls", None)
    content = (getattr(m, "content", "") or "")[:200]
    name = getattr(m, "name", "")
    sys.stderr.write("%s name=%s tool_calls=%r content=%r\n" % (kind, name, tc, content))
sys.stderr.write("=== FINAL OUTPUT ===\n%s\n" % (r.get("output", "")[:500]))
