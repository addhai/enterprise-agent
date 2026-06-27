"""
MCP (Model Context Protocol) Server — 把客服工具暴露为标准化 MCP HTTP 接口

使用 zeromcp (McpServer, 1.4.0) 实现 HTTP 模式 MCP Server。
任意 MCP 兼容的 Agent（Claude Desktop、Claude Agent SDK、自定义 Agent 等）
通过 HTTP 连接后可以自动发现并调用这三个工具。

启动方式:
  python -m src.protocols.mcp_server

启动后:
  MCP Endpoint:  http://localhost:9000/mcp
  SSE Endpoint:  http://localhost:9000/sse

跨框架调用示例:
  1. 本服务启动后监听 9000 端口
  2. Claude Agent SDK Agent 配置 MCP 客户端指向 http://localhost:9000/mcp
  3. 自动发现 3 个工具: search_knowledge_base, search_faq, escalate_to_human
  4. Agent 按 MCP 协议发起 tools/call → 本服务执行并返回结果
"""

import logging
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from zeromcp import McpServer

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def build_mcp_server() -> McpServer:
    """构建 MCP Server，注册客服工具

    Returns:
        McpServer 实例，已注册 search_knowledge_base, search_faq, escalate_to_human
    """
    from src.agent.tools import create_tools

    server = McpServer(
        name="enterprise-customer-service",
        version="1.0.0",
    )

    tools = create_tools(retriever=None, user_id="mcp_agent")

    for tool in tools:
        # zeromcp 的 McpServer.tool() 返回装饰器，直接装饰函数即可
        server.tool(tool.func)

    logger.info("Registered %d MCP tools: %s", len(tools), [t.name for t in tools])
    return server


if __name__ == "__main__":
    server = build_mcp_server()

    # HTTP 模式：启动真正的 HTTP 服务器并保持运行
    logger.info("Starting MCP HTTP Server on http://localhost:9000")
    logger.info("  Streamable HTTP: http://localhost:9000/mcp")
    logger.info("  SSE:              http://localhost:9000/sse")
    logger.info("")
    logger.info("Any MCP-compatible agent can now:")
    logger.info("  1. Connect to http://localhost:9000/mcp")
    logger.info("  2. Call initialize → discover tools")
    logger.info("  3. Call tools/call → invoke search_knowledge_base etc.")

    # serve() 默认 background=True，返回后主线程退出会关闭服务器
    # 所以这里 background=False 来阻塞主线程保持运行
    server.serve(host="0.0.0.0", port=9000, background=False)
