"""接地重答有效性实验 + chunk 完整性检查。

问题背景：激光定位灯不亮，工具已返回含「故障3」表格的 chunk，但
qwen2.5:7b 自己输出成「故障4 屏幕闪烁」+ 发射率/光斑等幻觉内容。

本脚本回答两个问题：
  Q1. 被检索到的 chunk 本身是否完整（表格有没有被切成两段）？
  Q2. 把同一批文档交给「文档置顶 + 禁外部常识」的接地重答，能否答对？
      若答对 → 说明问题在生成阶段的上下文/忠实度，重答机制可用；
      若答错 → 说明 chunk 内容本身残缺，得回到切块策略。

用法：docker exec thermo-intranet python scripts/probe_rescue_effect.py
"""

import sys

sys.path.insert(0, "/app")

from src.graph.nodes import _grounded_rescue_answer  # noqa: E402
from src.rag.retriever import HybridRetriever  # noqa: E402

LEVELS = ["public", "internal", "confidential", "restricted"]
retriever = HybridRetriever()

QUERIES = ["激光定位灯不亮怎么处理？", "校准对环境有什么要求？"]

for q in QUERIES:
    docs = retriever.search(
        q,
        top_k=5,
        user_id="probe",
        tenant_id="default",
        user_access_levels=LEVELS,
    )
    print("=" * 74)
    print("QUERY:", q, "| 命中", len(docs), "条")
    for i, d in enumerate(docs, start=1):
        text = d.page_content or ""
        src = (d.metadata or {}).get("source", "?")
        print(f"\n--- Doc{i} src={src} len={len(text)}")
        print(text)
    print("\n>>> 接地重答输出：")
    print(_grounded_rescue_answer(q, docs))
