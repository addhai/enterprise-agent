"""Slack MCP 工具 — 消息发送、频道管理、用户查询

使用 Slack Web API (https://api.slack.com/methods)。
"""
import logging
from typing import Callable, List, Optional

from langchain_core.tools import tool

from src.agent.tools import PermissionChecker
from src.config import settings
from src.mcp_tools.common import format_result, require_admin

logger = logging.getLogger(__name__)


def _slack_request(method: str, endpoint: str, params: dict = None, body: dict = None) -> dict:
    """Slack API 请求"""
    import httpx

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "enterprise-agent",
    }
    if settings.mcp_slack_token:
        headers["Authorization"] = f"Bearer {settings.mcp_slack_token}"

    url = f"https://slack.com/api/{endpoint}"
    try:
        if method.upper() == "GET":
            resp = httpx.get(url, headers=headers, params=params, timeout=15)
        else:
            resp = httpx.post(url, headers=headers, json=body, timeout=15)
        if resp.status_code >= 400:
            return {"error": True, "status": resp.status_code, "message": resp.text}
        result = resp.json()
        if not result.get("ok"):
            return {"error": True, "message": result.get("error", "Unknown error")}
        return result
    except Exception as e:
        logger.error("Slack API error: %s", e)
        return {"error": True, "message": str(e)}


def create_slack_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建 Slack 工具集"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    if not settings.mcp_slack_enabled:
        @tool
        def slack_send_message(channel: str = "", text: str = "") -> str:
            """Slack 工具（未启用）。"""
            return format_result("未启用", "Slack MCP 服务未启用，请在配置中开启 mcp_slack_enabled")

        return [slack_send_message]

    @tool
    def slack_send_message(channel: str, text: str, blocks: str = "") -> str:
        """发送消息到 Slack 频道。

        何时使用：需要向团队成员发送通知、告警或更新时。

        Args:
            channel: 频道 ID 或名称，如 #general、@username、C1234567890
            text: 消息文本（支持 Markdown）
            blocks: 消息块（JSON 字符串，可选）
        """
        if not checker.check("slack_send_message"):
            return format_result("权限不足", "您没有权限发送 Slack 消息")

        if not channel or not text:
            return format_result("参数错误", "channel 和 text 不能为空")

        body = {"channel": channel, "text": text}
        if blocks:
            import json
            try:
                body["blocks"] = json.loads(blocks)
            except json.JSONDecodeError:
                return format_result("参数错误", "blocks 必须是有效的 JSON 字符串")

        result = _slack_request("POST", "chat.postMessage", body=body)
        if result.get("error"):
            return format_result("发送失败", result.get("message", "未知错误"))

        return format_result("发送成功", "", {
            "channel": result.get("channel", ""),
            "ts": result.get("ts", ""),
            "message": result.get("message", {}).get("text", "")[:100],
        })

    @tool
    def slack_list_channels(
        types: str = "public_channel,private_channel",
        limit: int = 100,
    ) -> str:
        """列出 Slack 工作空间中的频道。

        何时使用：需要查看可用频道列表时。

        Args:
            types: 频道类型，逗号分隔，如 public_channel,private_channel,mpim,im
            limit: 返回数量限制，默认 100
        """
        if not checker.check("slack_list_channels"):
            return format_result("权限不足", "您没有权限查看 Slack 频道")

        params = {"types": types, "limit": limit}
        result = _slack_request("GET", "conversations.list", params=params)
        if result.get("error"):
            return format_result("查询失败", result.get("message", "未知错误"))

        channels = result.get("channels", [])
        lines = [f"[查询成功] 共 {len(channels)} 个频道:"]
        for ch in channels:
            is_private = ch.get("is_private", False)
            is_archived = ch.get("is_archived", False)
            prefix = "🔒" if is_private else "📢"
            suffix = " (已归档)" if is_archived else ""
            lines.append(
                f"  {prefix} {ch.get('name', '')} [ID: {ch.get('id', '')}]"
                f" ({ch.get('num_members', 0)} 成员){suffix}"
            )
        return "\n".join(lines)

    @tool
    def slack_get_channel_info(channel: str) -> str:
        """获取 Slack 频道的详细信息。

        何时使用：需要了解频道的成员、主题、目的等信息时。

        Args:
            channel: 频道 ID 或名称
        """
        if not checker.check("slack_get_channel_info"):
            return format_result("权限不足", "您没有权限查看频道信息")

        if not channel:
            return format_result("参数错误", "channel 不能为空")

        result = _slack_request("GET", "conversations.info", params={"channel": channel})
        if result.get("error"):
            return format_result("查询失败", result.get("message", "未知错误"))

        ch = result.get("channel", {})
        return format_result("查询成功", "", {
            "id": ch.get("id", ""),
            "name": ch.get("name", ""),
            "topic": ch.get("topic", {}).get("value", "")[:100] if ch.get("topic") else "",
            "purpose": ch.get("purpose", {}).get("value", "")[:100] if ch.get("purpose") else "",
            "num_members": ch.get("num_members", 0),
            "is_private": ch.get("is_private", False),
            "is_archived": ch.get("is_archived", False),
            "created": ch.get("created", ""),
        })

    @tool
    def slack_list_users(limit: int = 100, cursor: str = "") -> str:
        """列出 Slack 工作空间中的用户。

        何时使用：需要查看团队成员列表时。

        Args:
            limit: 返回数量限制，默认 100
            cursor: 分页游标（用于翻页）
        """
        if not checker.check("slack_list_users"):
            return format_result("权限不足", "您没有权限查看用户列表")

        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        result = _slack_request("GET", "users.list", params=params)
        if result.get("error"):
            return format_result("查询失败", result.get("message", "未知错误"))

        users = result.get("members", [])
        lines = [f"[查询成功] 共 {len(users)} 个用户:"]
        for user in users:
            if user.get("deleted", False):
                continue
            status_emoji = user.get("profile", {}).get("status_emoji", "")
            lines.append(
                f"  • {user.get('real_name', '')} (@{user.get('name', '')}) "
                f"[ID: {user.get('id', '')}]{status_emoji}"
            )
        return "\n".join(lines)

    @tool
    def slack_get_user_info(user: str) -> str:
        """获取 Slack 用户的详细信息。

        何时使用：需要了解某个用户的资料、状态等信息时。

        Args:
            user: 用户 ID 或用户名（@username）
        """
        if not checker.check("slack_get_user_info"):
            return format_result("权限不足", "您没有权限查看用户信息")

        if not user:
            return format_result("参数错误", "user 不能为空")

        user_id = user.lstrip("@")
        result = _slack_request("GET", "users.info", params={"user": user_id})
        if result.get("error"):
            return format_result("查询失败", result.get("message", "未知错误"))

        u = result.get("user", {})
        profile = u.get("profile", {})
        return format_result("查询成功", "", {
            "id": u.get("id", ""),
            "name": u.get("name", ""),
            "real_name": u.get("real_name", ""),
            "email": profile.get("email", ""),
            "title": profile.get("title", ""),
            "status_text": profile.get("status_text", ""),
            "status_emoji": profile.get("status_emoji", ""),
            "team": u.get("team_id", ""),
        })

    @tool
    def slack_search_messages(
        query: str,
        channel: str = "",
        count: int = 20,
        sort: str = "timestamp",
    ) -> str:
        """搜索 Slack 消息。

        何时使用：需要查找历史消息、关键词搜索时。

        Args:
            query: 搜索关键词
            channel: 频道 ID（限定频道时使用）
            count: 返回数量，默认 20
            sort: 排序方式，timestamp（时间）或 score（相关性）
        """
        if not checker.check("slack_search_messages"):
            return format_result("权限不足", "您没有权限搜索消息")

        if not query:
            return format_result("参数错误", "query 不能为空")

        params = {"query": query, "count": count, "sort": sort}
        if channel:
            params["channel"] = channel

        result = _slack_request("GET", "search.messages", params=params)
        if result.get("error"):
            return format_result("搜索失败", result.get("message", "未知错误"))

        matches = result.get("messages", {}).get("matches", [])
        lines = [f"[搜索完成] 共 {len(matches)} 个结果:"]
        for msg in matches:
            channel_name = msg.get("channel", {}).get("name", "")
            user_name = msg.get("user", "")
            preview = msg.get("text", "")[:80]
            ts = msg.get("ts", "")
            lines.append(f"  • [{channel_name}] @{user_name} ({ts}): {preview}")
        return "\n".join(lines)

    @tool
    def slack_create_channel(name: str, is_private: bool = False) -> str:
        """创建 Slack 频道。

        何时使用：需要创建新的团队频道时。

        Args:
            name: 频道名称（小写字母、数字、连字符）
            is_private: 是否私有频道，默认 False（公开）
        """
        if not require_admin(checker, "slack_create_channel"):
            return format_result("权限不足", "需要 admin 角色才能创建频道")

        if not name:
            return format_result("参数错误", "name 不能为空")

        body = {"name": name, "is_private": is_private}
        result = _slack_request("POST", "conversations.create", body=body)
        if result.get("error"):
            return format_result("创建失败", result.get("message", "未知错误"))

        ch = result.get("channel", {})
        return format_result("创建成功", "", {
            "id": ch.get("id", ""),
            "name": ch.get("name", ""),
            "is_private": ch.get("is_private", False),
        })

    return [
        slack_send_message,
        slack_list_channels,
        slack_get_channel_info,
        slack_list_users,
        slack_get_user_info,
        slack_search_messages,
        slack_create_channel,
    ]
