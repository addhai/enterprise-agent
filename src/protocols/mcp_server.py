"""
MCP (Model Context Protocol) Server — 把客服工具暴露为标准化 MCP 接口

使用 zeromcp 实现零依赖 MCP Server。
任意 MCP 兼容的 Agent（Claude Desktop、自定义 Agent 等）连接后
可以自动发现并调用这三个工具。

启动方式: python -m src.protocols.mcp_server
"""

import logging
from zeromcp import create_server
from src.agent.tools import create_tools

logger = logging.getLogger(__name__)


def build_mcp_server():
    """构建 MCP Server，注册客服工具"""

    tools = create_tools(retriever=None, user_id="mcp_agent")

    server = create_server(
        name="enterprise-customer-service",
        version="1.0.0",
        description="CloudSync 企业客服 Agent —— 提供产品知识库搜索、FAQ 匹配、人工转接能力",
    )

    for tool in tools:
        server.tool(tool.func, name=tool.name, description=tool.description)

    return server


if __name__ == "__main__":
    server = build_mcp_server()
    logger.info("MCP Server starting on http://localhost:9000")
    server.run(transport="stdio")
