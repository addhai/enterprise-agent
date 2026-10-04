"""检索 A/B 取证：打印 search_knowledge_base 工具真正交给模型的文档原文。

目的：隔离「检索结果差异」与「模型随机性」。同一份工具输出文本若在两版
检索器下不同，即可判定行为差异来自检索侧。

用法（容器内，切换 retriever.py 前后各跑一次）：
  docker exec thermo-intranet python scripts/probe_tool_docs.py
"""

import sys

sys.path.insert(0, "/app")

from src.agent.tools import create_tools  # noqa: E402
from src.rag.retriever import HybridRetriever  # noqa: E402

LEVELS = ["public", "internal", "confidential", "restricted"]

retriever = HybridRetriever()
tools = create_tools(
    retriever=retriever,
    user_id="probe",
    tenant_id="default",
    user_access_levels=LEVELS,
)
kb = [t for t in tools if t.name == "search_knowledge_base"][0]

QUERIES = [
    "T100 测温范围",
    "激光定位灯不亮",
    "保修期",
    "校准环境要求",
    "切换温度单位",
]
MARKERS = [
    "激光定位灯不亮",
    "激光模组",
    "出光孔",
    "20℃ ± 3℃",
    "≤60% RH",
    "30分钟",
    "环境温度",
]

for q in QUERIES:
    out = kb.invoke({"query": q})
    print("=" * 74)
    print(f"QUERY: {q} | 工具返回长度: {len(out)}")
    print("命中文档（按顺序）：")
    for line in out.splitlines():
        if line.startswith("[Doc "):
            print("   ", line.strip())
    print("关键事实是否在交给模型的文本中：")
    for m in MARKERS:
        print(f"    {m!r}: {m in out}")
    print("前 300 字预览：")
    print("   ", out[:300].replace("\n", " "))
