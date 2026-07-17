"""飞书 MCP 工具 — 消息通知与用户管理

支持发送文本消息、卡片消息、获取用户信息等。
使用飞书开放平台 API（https://open.feishu.cn/open-apis）。

替代钉钉 MCP 工具。
"""
import json
import logging
import time
from typing import Callable, List, Optional

from langchain_core.tools import tool

from src.agent.tools import PermissionChecker
from src.config import settings
from src.mcp_tools.common import format_result

logger = logging.getLogger(__name__)

# 飞书 API 基础地址
_FEISHU_BASE = "https://open.feishu.cn/open-apis"

# token 缓存
_token_cache = {"token": "", "expires_at": 0}


def _get_feishu_token() -> str:
    """获取飞书 tenant_access_token（带缓存）"""
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]

    import httpx

    url = f"{_FEISHU_BASE}/auth/v3/tenant_access_token/internal"
    body = {
        "app_id": settings.mcp_feishu_app_id,
        "app_secret": settings.mcp_feishu_app_secret,
    }

    try:
        resp = httpx.post(url, json=body, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            token = data["tenant_access_token"]
            _token_cache["token"] = token
            _token_cache["expires_at"] = time.time() + data.get("expire", 7000)
            return token
        logger.error("Feishu token error: %s", data)
        return ""
    except Exception as e:
        logger.error("Feishu token request failed: %s", e)
        return ""


def _feishu_request(
    method: str,
    path: str,
    params: dict = None,
    body: dict = None,
) -> dict:
    """飞书 API 请求"""
    import httpx

    token = _get_feishu_token()
    if not token:
        return {"code": -1, "msg": "无法获取 tenant_access_token"}

    url = f"{_FEISHU_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

    try:
        if method == "GET":
            resp = httpx.get(url, params=params, headers=headers, timeout=10)
        else:
            resp = httpx.post(url, json=body, params=params, headers=headers, timeout=10)
        return resp.json()
    except Exception as e:
        logger.error("Feishu API error: %s", e)
        return {"code": -1, "msg": str(e)}


def create_feishu_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建飞书消息与通知工具"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    if not settings.mcp_feishu_enabled:
        @tool
        def feishu_send_message(receive_id: str, content: str) -> str:
            """飞书发送消息（未启用）。"""
            return format_result("未启用", "飞书 MCP 服务未启用，请在配置中开启 mcp_feishu_enabled")

        return [feishu_send_message]

    @tool
    def feishu_send_text(receive_id: str, text: str, receive_id_type: str = "open_id") -> str:
        """发送飞书文本消息。

        何时使用：需要给飞书用户发送文本通知时使用。

        Args:
            receive_id: 接收者 ID（open_id / user_id / chat_id / email）
            text: 消息内容
            receive_id_type: 接收者 ID 类型，默认 open_id，可选: open_id / user_id / chat_id / email
        """
        if not checker.check("feishu_send_text"):
            return format_result("权限不足", "您没有权限发送飞书消息")

        body = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        }
        result = _feishu_request("POST", "/im/v1/messages", params={"receive_id_type": receive_id_type}, body=body)

        if result.get("code") == 0:
            msg_id = result.get("data", {}).get("message_id", "")
            return format_result("发送成功", "", {"message_id": msg_id})
        return format_result("发送失败", result.get("msg", "未知错误"))

    @tool
    def feishu_send_card(
        receive_id: str,
        title: str,
        content: str,
        receive_id_type: str = "open_id",
    ) -> str:
        """发送飞书卡片消息（带标题和正文）。

        何时使用：需要发送带格式的富文本通知时使用。

        Args:
            receive_id: 接收者 ID
            title: 卡片标题
            content: 卡片内容（纯文本）
            receive_id_type: 接收者 ID 类型，默认 open_id
        """
        if not checker.check("feishu_send_card"):
            return format_result("权限不足", "您没有权限发送飞书消息")

        card = {
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
            ],
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "turquoise",
            },
        }
        body = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        }
        result = _feishu_request("POST", "/im/v1/messages", params={"receive_id_type": receive_id_type}, body=body)

        if result.get("code") == 0:
            msg_id = result.get("data", {}).get("message_id", "")
            return format_result("发送成功", "", {"message_id": msg_id})
        return format_result("发送失败", result.get("msg", "未知错误"))

    @tool
    def feishu_send_chat_message(chat_id: str, text: str) -> str:
        """发送飞书群消息（文本）。

        何时使用：需要向飞书群发送通知时使用。

        Args:
            chat_id: 群聊 ID
            text: 消息内容
        """
        if not checker.check("feishu_send_chat_message"):
            return format_result("权限不足", "您没有权限发送飞书群消息")

        body = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        }
        result = _feishu_request("POST", "/im/v1/messages", params={"receive_id_type": "chat_id"}, body=body)

        if result.get("code") == 0:
            msg_id = result.get("data", {}).get("message_id", "")
            return format_result("发送成功", "", {"message_id": msg_id})
        return format_result("发送失败", result.get("msg", "未知错误"))

    @tool
    def feishu_get_user_info(user_id: str, user_id_type: str = "open_id") -> str:
        """获取飞书用户详细信息。

        何时使用：需要查询用户的姓名、邮箱、部门等信息时。

        Args:
            user_id: 用户 ID
            user_id_type: ID 类型，默认 open_id，可选: open_id / user_id / mobile / email
        """
        if not checker.check("feishu_get_user_info"):
            return format_result("权限不足", "您没有权限查询用户信息")

        result = _feishu_request(
            "GET",
            f"/contact/v3/users/{user_id}",
            params={"user_id_type": user_id_type},
        )

        if result.get("code") == 0:
            user = result.get("data", {}).get("user", {})
            return format_result("查询成功", "", {
                "name": user.get("name", ""),
                "email": user.get("email", ""),
                "mobile": user.get("mobile", ""),
                "department_ids": str(user.get("department_ids", [])),
                "position": user.get("title", ""),
                "employee_no": user.get("employee_no", ""),
            })
        return format_result("查询失败", result.get("msg", "未知错误"))

    @tool
    def feishu_list_departments(page_size: int = 50) -> str:
        """获取飞书部门列表。

        何时使用：需要查看组织架构、部门列表时。

        Args:
            page_size: 每页数量，默认 50
        """
        if not checker.check("feishu_list_departments"):
            return format_result("权限不足", "您没有权限查询部门信息")

        result = _feishu_request(
            "GET",
            "/contact/v3/departments",
            params={"page_size": page_size, "fetch_child": False},
        )

        if result.get("code") == 0:
            items = result.get("data", {}).get("items", [])
            lines = [f"[查询成功] 共 {len(items)} 个部门:"]
            for d in items:
                lines.append(f"  • [{d.get('department_id', '')}] {d.get('name', '')}")
            return "\n".join(lines)
        return format_result("查询失败", result.get("msg", "未知错误"))

    return [
        feishu_send_text,
        feishu_send_card,
        feishu_send_chat_message,
        feishu_get_user_info,
        feishu_list_departments,
    ]
