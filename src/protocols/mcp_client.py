"""
MCP Client — 客服 Agent 作为 Client 消费外部 MCP 服务

客服 Agent 可以连接到外部 MCP Server（如 GitHub MCP、Slack MCP），
发现并调用其工具，实现跨服务协作。

架构:
  客服 Agent (Client) ──MCP HTTP──→ 外部 MCP Server (GitHub/Slack)
  客服 Agent 收到用户请求后，通过 MCP Client 调用外部工具获取数据，
  再将结果整合为用户友好的回复。

使用方式:
  from src.protocols.mcp_client import McpClient

  # 连接到外部 MCP Server
  client = McpClient("http://localhost:9000/mcp")

  # 发现可用工具
  tools = client.discover_tools()

  # 调用工具
  result = client.call_tool("github_get_repo", {"owner": "cloudsync", "repo": "core"})
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MCP_CLIENT_AVAILABLE = False
try:
    from zeromcp import McpClient as ZeroMcpClient
    _MCP_CLIENT_AVAILABLE = True
except ImportError:
    ZeroMcpClient = None


class McpClient:
    """MCP Client 包装器 — 连接外部 MCP Server"""

    def __init__(self, server_url: str, timeout: int = 30):
        """初始化 MCP Client

        Args:
            server_url: 外部 MCP Server 的 URL（如 http://localhost:9000/mcp）
            timeout: 超时秒数
        """
        self.server_url = server_url
        self.timeout = timeout
        self._client = None
        self._tools_cache = None
        self._initialized = False

    def _get_client(self):
        """延迟创建 MCP Client 实例"""
        if self._client is None:
            if not _MCP_CLIENT_AVAILABLE:
                raise RuntimeError(
                    "zeromcp 未安装，无法创建 MCP Client。"
                    "请安装 zeromcp: pip install zeromcp"
                )
            self._client = ZeroMcpClient(url=self.server_url)
        return self._client

    def initialize(self) -> bool:
        """初始化连接，执行 MCP initialize 握手"""
        try:
            client = self._get_client()
            client.initialize()
            self._initialized = True
            logger.info("MCP Client initialized: %s", self.server_url)
            return True
        except Exception as e:
            logger.error("Failed to initialize MCP Client: %s", e)
            return False

    def discover_tools(self) -> List[Dict[str, Any]]:
        """发现外部 MCP Server 上的可用工具

        Returns:
            工具列表，每个工具包含 name、description、parameters 等信息
        """
        if not self._initialized:
            self.initialize()

        if self._tools_cache is not None:
            return self._tools_cache

        try:
            client = self._get_client()
            tools = client.describe_tools()
            self._tools_cache = tools
            logger.info("Discovered %d tools from %s", len(tools), self.server_url)
            return tools
        except Exception as e:
            logger.error("Failed to discover tools: %s", e)
            return []

    def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> Optional[str]:
        """调用外部 MCP Server 上的工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数（字典）

        Returns:
            工具返回结果（字符串），失败时返回 None
        """
        if not self._initialized:
            self.initialize()

        try:
            client = self._get_client()
            arguments = arguments or {}
            logger.info("Calling tool: %s with args: %s", tool_name, arguments)

            result = client.call_tool(tool_name, arguments)
            logger.debug("Tool result: %s", str(result)[:200])
            return str(result)

        except Exception as e:
            logger.error("Failed to call tool %s: %s", tool_name, e)
            return None

    def get_tool_description(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取指定工具的详细描述

        Args:
            tool_name: 工具名称

        Returns:
            工具描述（包含 name、description、parameters），不存在时返回 None
        """
        tools = self.discover_tools()
        for tool in tools:
            if tool.get("name") == tool_name:
                return tool
        return None

    def is_tool_available(self, tool_name: str) -> bool:
        """检查指定工具是否可用"""
        return self.get_tool_description(tool_name) is not None

    def close(self):
        """关闭连接"""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._initialized = False


def create_mcp_client(server_url: str) -> McpClient:
    """工厂函数：创建 MCP Client 实例"""
    return McpClient(server_url)


def call_external_mcp_tool(
    server_url: str,
    tool_name: str,
    arguments: Dict[str, Any] = None,
    timeout: int = 30,
) -> Optional[str]:
    """便捷函数：一次性调用外部 MCP 工具（自动创建和销毁连接）

    Args:
        server_url: 外部 MCP Server URL
        tool_name: 工具名称
        arguments: 工具参数
        timeout: 超时秒数

    Returns:
        工具返回结果，失败时返回 None
    """
    client = McpClient(server_url, timeout=timeout)
    try:
        return client.call_tool(tool_name, arguments)
    finally:
        client.close()
