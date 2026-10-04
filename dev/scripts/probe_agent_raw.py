"""Agent 原始输出取证：看 ReAct 到底产出了什么，才被判为空/清空。

用法（容器内）：
  docker exec thermo-intranet python scripts/probe_agent_raw.py
"""

import sys

sys.path.insert(0, "/app")

from src.agent.agent import CustomerServiceAgent  # noqa: E402
from src.rag.retriever import HybridRetriever  # noqa: E402

LEVELS = ["public", "internal", "confidential", "restricted"]
retriever = HybridRetriever()

QUERIES = ["激光定位灯不亮怎么处理？", "校准对环境有什么要求？"]

for q in QUERIES:
    print("=" * 74)
    print("QUERY:", q)
    agent = CustomerServiceAgent(
        retriever=retriever,
        user_id="probe",
        tenant_id="default",
        user_access_levels=LEVELS,
    )
    result = agent.run_with_trace(q)
    print("[原始 output] repr 前 500：")
    print(repr(result.get("output"))[:500])
    steps = result.get("intermediate_steps", []) or []
    print(f"[intermediate_steps 数量] {len(steps)}")
    for i, step in enumerate(steps, start=1):
        action = getattr(step, "action", None) or (
            step[0] if isinstance(step, tuple) else None
        )
        tool = getattr(action, "tool", "?")
        tool_input = getattr(action, "tool_input", "?")
        obs = getattr(step, "observation", None)
        if obs is None and isinstance(step, tuple) and len(step) > 1:
            obs = step[1]
        obs_text = str(obs)
        print(f"  step{i}: tool={tool} input={tool_input} obs_len={len(obs_text)}")
        print(f"          obs 前 120: {obs_text[:120]!r}")
    print("[messages 类型序列]")
    for m in result.get("messages", [])[-6:]:
        content = getattr(m, "content", "")
        print(f"    {type(m).__name__}: {str(content)[:160]!r}")
