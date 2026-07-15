"""钉钉 MCP 工具 — 消息通知与用户管理

支持发送工作通知、群消息、获取用户信息等。
使用钉钉开放平台 API（https://oapi.dingtalk.com）。
"""
import logging
import time
from typing import Callable, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agent.tools import PermissionChecker
from src.config import settings
from src.mcp_tools.common import format_result, require_admin

logger = logging.getLogger(__name__)

_access_token_cache = {"token": "", "expires_at": 0}


def _get_dingtalk_token() -> str:
    """获取钉钉 access_token（带缓存）"""
    if _access_token_cache["token"] and time.time() < _access_token_cache["expires_at"]:
        return _access_token_cache["token"]

    import httpx

    url = "https://oapi.dingtalk.com/gettoken"
    params = {
        "appkey": settings.mcp_dingtalk_app_key,
        "appsecret": settings.mcp_dingtalk_app_secret,
    }

    try:
        resp = httpx.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("errcode") == 0:
            token = data["access_token"]
            _access_token_cache["token"] = token
            _access_token_cache["expires_at"] = time.time() + data.get("expires_in", 7000)
            return token
        logger.error("DingTalk token error: %s", data)
        return ""
    except Exception as e:
        logger.error("DingTalk token request failed: %s", e)
        return ""


def _dingtalk_post(path: str, body: dict) -> dict:
    """钉钉 API POST 请求"""
    import httpx

    token = _get_dingtalk_token()
    if not token:
        return {"errcode": -1, "errmsg": "无法获取 access_token"}

    url = f"https://oapi.dingtalk.com{path}?access_token={token}"
    try:
        resp = httpx.post(url, json=body, timeout=10)
        return resp.json()
    except Exception as e:
        logger.error("DingTalk API error: %s", e)
        return {"errcode": -1, "errmsg": str(e)}


def create_dingtalk_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建钉钉消息与通知工具"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    if not settings.mcp_dingtalk_enabled:
        @tool
        def dingtalk_send_message(user_id_list: str, content: str) -> str:
            """钉钉发送消息（未启用）。"""
            return format_result("未启用", "钉钉 MCP 服务未启用，请在配置中开启 mcp_dingtalk_enabled")

        return [dingtalk_send_message]

    @tool
    def dingtalk_send_text(user_id_list: str, content: str) -> str:
        """发送钉钉工作通知（文本消息）。

        何时使用：需要给钉钉用户发送文本通知时使用。

        Args:
            user_id_list: 接收者用户 ID 列表，逗号分隔，如 "user1,user2"
            content: 消息内容
        """
        if not checker.check("dingtalk_send_text"):
            return format_result("权限不足", "您没有权限发送钉钉消息")

        body = {
            "agent_id": settings.mcp_dingtalk_agent_id,
            "userid_list": user_id_list,
            "msg": {
                "msgtype": "text",
                "text": {"content": content},
            },
        }
        result = _dingtalk_post("/topapi/message/corpconversation/asyncsend_v2", body)

        if result.get("errcode") == 0:
            task_id = result.get("task_id", "")
            return format_result("发送成功", "", {"task_id": task_id})
        return format_result("发送失败", result.get("errmsg", "未知错误"))

    @tool
    def dingtalk_send_markdown(user_id_list: str, title: str, text: str) -> str:
        """发送钉钉 Markdown 工作通知。

        何时使用：需要发送带格式的富文本通知时使用。

        Args:
            user_id_list: 接收者用户 ID 列表，逗号分隔
            title: 消息标题
            text: Markdown 内容
        """
        if not checker.check("dingtalk_send_markdown"):
            return format_result("权限不足", "您没有权限发送钉钉消息")

        body = {
            "agent_id": settings.mcp_dingtalk_agent_id,
            "userid_list": user_id_list,
            "msg": {
                "msgtype": "markdown",
                "markdown": {"title": title, "text": text},
            },
        }
        result = _dingtalk_post("/topapi/message/corpconversation/asyncsend_v2", body)

        if result.get("errcode") == 0:
            return format_result("发送成功", "", {"task_id": result.get("task_id", "")})
        return format_result("发送失败", result.get("errmsg", "未知错误"))

    @tool
    def dingtalk_send_action_card(
        user_id_list: str,
        title: str,
        text: str,
        single_title: str = "查看详情",
        single_url: str = "",
    ) -> str:
        """发送钉钉 ActionCard 卡片消息（带跳转按钮）。

        何时使用：需要发送带操作按钮的卡片通知时使用。

        Args:
            user_id_list: 接收者用户 ID 列表，逗号分隔
            title: 卡片标题
            text: 卡片内容（Markdown）
            single_title: 按钮文字，默认"查看详情"
            single_url: 点击跳转的 URL
        """
        if not checker.check("dingtalk_send_action_card"):
            return format_result("权限不足", "您没有权限发送钉钉消息")

        body = {
            "agent_id": settings.mcp_dingtalk_agent_id,
            "userid_list": user_id_list,
            "msg": {
                "msgtype": "action_card",
                "action_card": {
                    "title": title,
                    "markdown": text,
                    "single_title": single_title,
                    "single_url": single_url,
                },
            },
        }
        result = _dingtalk_post("/topapi/message/corpconversation/asyncsend_v2", body)

        if result.get("errcode") == 0:
            return format_result("发送成功", "", {"task_id": result.get("task_id", "")})
        return format_result("发送失败", result.get("errmsg", "未知错误"))

    @tool
    def dingtalk_get_user_info(user_id: str) -> str:
        """获取钉钉用户详细信息。

        何时使用：需要查询用户的部门、职位、邮箱等信息时。

        Args:
            user_id: 钉钉用户 ID
        """
        if not checker.check("dingtalk_get_user_info"):
            return format_result("权限不足", "您没有权限查询用户信息")

        result = _dingtalk_post("/topapi/v2/user/get", {"userid": user_id})

        if result.get("errcode") == 0:
            user = result.get("result", {})
            return format_result("查询成功", "", {
                "name": user.get("name", ""),
                "email": user.get("email", ""),
                "mobile": user.get("mobile", ""),
                "department": str(user.get("dept_id_list", [])),
                "position": user.get("position", ""),
                "job_number": user.get("job_number", ""),
            })
        return format_result("查询失败", result.get("errmsg", "未知错误"))

    @tool
    def dingtalk_list_departments(dept_id: int = 1) -> str:
        """获取部门列表。

        何时使用：需要查看组织架构、部门列表时。

        Args:
            dept_id: 父部门 ID，默认 1（根部门）
        """
        if not checker.check("dingtalk_list_departments"):
            return format_result("权限不足", "您没有权限查询部门信息")

        result = _dingtalk_post("/topapi/v2/department/listsub", {"dept_id": dept_id})

        if result.get("errcode") == 0:
            depts = result.get("result", [])
            lines = [f"[查询成功] 共 {len(depts)} 个子部门:"]
            for d in depts:
                lines.append(f"  • [{d.get('dept_id', '')}] {d.get('name', '')}")
            return "\n".join(lines)
        return format_result("查询失败", result.get("errmsg", "未知错误"))

    @tool
    def dingtalk_get_department_users(dept_id: int, cursor: int = 0, size: int = 20) -> str:
        """获取部门用户列表。

        何时使用：需要查看某个部门下的成员列表时。

        Args:
            dept_id: 部门 ID
            cursor: 分页游标，默认 0
            size: 每页数量，默认 20
        """
        if not checker.check("dingtalk_get_department_users"):
            return format_result("权限不足", "您没有权限查询部门用户")

        body = {"dept_id": dept_id, "cursor": cursor, "size": size}
        result = _dingtalk_post("/topapi/user/list", body)

        if result.get("errcode") == 0:
            users = result.get("result", {}).get("list", [])
            has_more = result.get("result", {}).get("has_more", False)
            lines = [f"[查询成功] 部门 {dept_id} 成员（{len(users)} 人，更多={has_more}）:"]
            for u in users:
                lines.append(f"  • [{u.get('userid', '')}] {u.get('name', '')} - {u.get('position', '')}")
            return "\n".join(lines)
        return format_result("查询失败", result.get("errmsg", "未知错误"))

    return [
        dingtalk_send_text,
        dingtalk_send_markdown,
        dingtalk_send_action_card,
        dingtalk_get_user_info,
        dingtalk_list_departments,
        dingtalk_get_department_users,
    ]
