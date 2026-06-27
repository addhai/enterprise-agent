"""A2A + MCP 协议集成演示脚本

展示：客服 Agent 如何通过 A2A 委托任务给其他 Agent，
以及如何通过 MCP 暴露工具。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def demo_mcp():
    """演示 MCP：注册工具并打印元数据"""
    print("=" * 60)
    print("MCP Protocol — Tool Registration Demo")
    print("=" * 60)

    from src.agent.tools import create_tools

    tools = create_tools(retriever=None, user_id="mcp_demo")

    print("\nRegistered MCP Tools:")
    for tool in tools:
        print(f"  • {tool.name}")
        print(f"    Description: {tool.description[:100]}...")
        print()

    print("MCP Server 启动命令: python -m src.protocols.mcp_server")
    print("Agent 连接后可自动发现以上工具并按 MCP 协议调用。")


async def demo_a2a():
    """演示 A2A：打印 Agent Card 内容"""
    print("\n" + "=" * 60)
    print("A2A Protocol — Agent Card Demo")
    print("=" * 60)

    from src.protocols.a2a_server import SERVICE_AGENT_CARD

    card = SERVICE_AGENT_CARD
    print(f"\nAgent Name: {card.name}")
    print(f"Version:    {card.version}")
    print(f"Streaming:  {card.capabilities.streaming}")
    print(f"\nSkills ({len(card.skills)}):")
    for skill in card.skills:
        print(f"  • {skill.name} [{skill.id}]")
        print(f"    {skill.description}")
        print(f"    Tags: {skill.tags}")
        print(f"    Examples: {skill.examples[:2]}")
        print()

    print("A2A Server 启动命令: python -m src.protocols.a2a_server")
    print("其他 Agent 可通过 http://localhost:9001/.well-known/agent.json 发现本 Agent。")
    print()


async def demo_a2a_delegation():
    """演示 A2A 委托流程（概念示意，不需要真实远程 Agent）"""
    print("=" * 60)
    print("A2A Delegation Flow — Concept Demo")
    print("=" * 60)

    print("""
场景：用户反馈 "My sync is stuck with 500GB file for 7 hours"

Step 1 — 客服 Agent 分析：
  → intent=technical
  → RAG 检索返回："大文件同步联系性能团队"
  → 判断：超出自身知识库范围

Step 2 — 客服 Agent 通过 A2A 委托给性能专家 Agent：
  → 拉取 Agent Card: http://perf-expert:9002/.well-known/agent.json
  → Agent Card 显示: "Performance Diagnosis Agent — 专精文件同步性能问题"
  → 委托 Task: "User sync stuck, 500GB file, 7 hours..."

Step 3 — 性能专家 Agent 执行：
  → 分析日志 → 发现是由于数据库锁冲突
  → 返回结论: "File lock conflict in DB. Recommend..."
  → Task 状态: completed

Step 4 — 客服 Agent 翻译结论为友好回复：
  "我们排查后发现是后台处理您的大文件时出现了锁冲突。
   建议您将文件分成小于 50GB 的批次分别上传。"
""")

    print("实现代码见: src/protocols/a2a_server.py → delegate_to_expert()")


async def main():
    await demo_mcp()
    await demo_a2a()
    await demo_a2a_delegation()


if __name__ == "__main__":
    asyncio.run(main())
