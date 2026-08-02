"""HITL 人工审批管理器 — 对齐 langgraph_multi-agent 的 humanloop_manager

参考：langgraph_multi-agent-rag-customer-support 的 GoHumanLoop + 飞书审批
本项目采用轻量级自研方案，复用现有飞书 MCP 配置：

工作流程：
    敏感操作触发 → 发送飞书审批卡片 → 等待人工审批 → 返回结果

与现有 human_node 的区别：
    - human_node：用户主动转人工，人工接管对话（interrupt 整个对话）
    - HumanLoopManager：敏感操作前请求审批（如删除/退款），人工批准后才执行

使用场景：
    1. 退款操作：客服 Agent 决定退款前，需人工审批
    2. 账户注销：执行注销前，需人工确认
    3. 大额订单修改：修改前需人工审批
    4. 敏感数据导出：导出前需人工审批

配置（.env）：
    HUMANLOOP_ENABLED=true              # 总开关
    HUMANLOOP_TIMEOUT=300               # 审批超时（秒，默认 5 分钟）
    HUMANLOOP_NOTIFY_CHANNEL=feishu     # 通知渠道（目前仅支持 feishu）
    # 复用 alert_feishu_receive_id 作为审批接收人
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from src.config import settings

logger = logging.getLogger(__name__)


class ApprovalStatus(str, Enum):
    """审批状态"""
    PENDING = "pending"        # 待审批
    APPROVED = "approved"      # 已批准
    REJECTED = "rejected"      # 已拒绝
    TIMEOUT = "timeout"        # 超时
    ERROR = "error"            # 错误


@dataclass
class ApprovalRequest:
    """审批请求"""
    request_id: str                              # 请求 ID
    action: str                                  # 待审批操作（如 "refund" / "delete_account"）
    description: str                             # 操作描述（人类可读）
    context: Dict[str, Any] = field(default_factory=dict)  # 操作上下文（金额、用户等）
    user_id: str = ""                            # 发起用户 ID
    session_id: str = ""                         # 会话 ID
    created_at: float = field(default_factory=time.time)   # 创建时间
    status: ApprovalStatus = ApprovalStatus.PENDING        # 当前状态
    reviewer_id: str = ""                        # 审批人 ID
    review_comment: str = ""                     # 审批意见
    reviewed_at: Optional[float] = None          # 审批时间


@dataclass
class ApprovalResult:
    """审批结果"""
    approved: bool                               # 是否批准
    status: ApprovalStatus                       # 审批状态
    request_id: str                              # 请求 ID
    reviewer_id: str = ""                        # 审批人
    comment: str = ""                            # 审批意见
    message: str = ""                            # 给 Agent 的消息


class HumanLoopManager:
    """人工审批管理器

    职责：
        1. 创建审批请求
        2. 通过飞书发送审批通知
        3. 等待人工审批（轮询/回调）
        4. 返回审批结果

    通知渠道：
        - 飞书卡片消息（复用现有飞书 MCP 配置）
        - 控制台日志（降级方案，无飞书时用）

    审批方式：
        - 飞书卡片按钮回调（需要配置飞书事件回调）
        - HTTP API 轮询（admin API 查询审批状态）

    与 human_node 的协作：
        HumanLoopManager 用于"操作前审批"（敏感操作执行前）
        human_node 用于"对话转人工"（用户主动要求人工服务）
    """

    def __init__(
        self,
        enabled: bool = None,
        timeout: int = None,
        notify_channel: str = None,
    ):
        self.enabled = enabled if enabled is not None else getattr(
            settings, "humanloop_enabled", False
        )
        self.timeout = timeout if timeout is not None else getattr(
            settings, "humanloop_timeout", 300
        )
        self.notify_channel = notify_channel or getattr(
            settings, "humanloop_notify_channel", "feishu"
        )
        # 审批请求存储（内存存储，生产环境应改用 Redis/DB）
        self._requests: Dict[str, ApprovalRequest] = {}

    def request_approval(
        self,
        action: str,
        description: str,
        context: Dict[str, Any] = None,
        user_id: str = "",
        session_id: str = "",
    ) -> ApprovalResult:
        """请求人工审批

        Args:
            action: 待审批操作标识（如 "refund" / "delete_account"）
            description: 操作描述（人类可读，会显示在审批卡片上）
            context: 操作上下文（如 {"amount": 100, "order_id": "xxx"}）
            user_id: 发起用户 ID
            session_id: 会话 ID

        Returns:
            ApprovalResult 审批结果

        注意：
            本方法是同步阻塞的，会等待审批结果或超时。
            在异步场景中应使用 async 版本（TODO）。
        """
        if not self.enabled:
            # 未启用审批，直接放行（默认允许）
            logger.info("HumanLoop disabled, auto-approving: action=%s", action)
            return ApprovalResult(
                approved=True,
                status=ApprovalStatus.APPROVED,
                request_id="",
                message="审批未启用，自动放行",
            )

        # 创建审批请求
        request = ApprovalRequest(
            request_id=f"HL-{uuid.uuid4().hex[:8]}",
            action=action,
            description=description,
            context=context or {},
            user_id=user_id,
            session_id=session_id,
        )
        self._requests[request.request_id] = request

        logger.info(
            "Approval requested: id=%s, action=%s, user=%s",
            request.request_id, action, user_id,
        )

        # 发送飞书通知
        self._send_notification(request)

        # 等待审批结果（轮询）
        result = self._wait_for_approval(request)

        return result

    def submit_review(
        self,
        request_id: str,
        approved: bool,
        reviewer_id: str = "",
        comment: str = "",
    ) -> bool:
        """提交审批结果（由人工审批后调用）

        Args:
            request_id: 审批请求 ID
            approved: 是否批准
            reviewer_id: 审批人 ID
            comment: 审批意见

        Returns:
            True 如果提交成功
        """
        request = self._requests.get(request_id)
        if not request:
            logger.warning("Approval request not found: %s", request_id)
            return False

        if request.status != ApprovalStatus.PENDING:
            logger.warning(
                "Approval request already reviewed: id=%s, status=%s",
                request_id, request.status,
            )
            return False

        request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        request.reviewer_id = reviewer_id
        request.review_comment = comment
        request.reviewed_at = time.time()

        logger.info(
            "Approval reviewed: id=%s, approved=%s, reviewer=%s",
            request_id, approved, reviewer_id,
        )
        return True

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """查询审批请求状态"""
        return self._requests.get(request_id)

    def list_pending(self) -> list:
        """列出所有待审批请求"""
        return [
            r for r in self._requests.values()
            if r.status == ApprovalStatus.PENDING
        ]

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _send_notification(self, request: ApprovalRequest) -> None:
        """发送审批通知到飞书"""
        if self.notify_channel != "feishu":
            logger.info(
                "Approval notification (channel=%s): id=%s, action=%s",
                self.notify_channel, request.request_id, request.action,
            )
            return

        # 复用 alert_feishu 配置
        receive_id = getattr(settings, "alert_feishu_receive_id", "")
        if not receive_id:
            logger.warning(
                "No alert_feishu_receive_id configured, "
                "approval notification will only log: id=%s",
                request.request_id,
            )
            return

        try:
            self._send_feishu_card(request, receive_id)
        except Exception as e:
            logger.warning(
                "Feishu notification failed, approval will wait silently: %s", e
            )

    def _send_feishu_card(self, request: ApprovalRequest, receive_id: str) -> None:
        """发送飞书审批卡片消息

        卡片包含两个按钮："批准" 和 "拒绝"，点击后回调到 admin API。
        """
        # 构建卡片内容
        context_str = "\n".join(
            f"  • {k}: {v}" for k, v in request.context.items()
        ) if request.context else "  （无）"

        card_content = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"[审批请求] {request.action}"},
                "template": "orange",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**操作描述：**\n{request.description}"},
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**操作上下文：**\n{context_str}"},
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**发起用户：** {request.user_id or '未知'}"},
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**请求 ID：** {request.request_id}"},
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "✅ 批准"},
                            "type": "primary",
                            "value": {
                                "request_id": request.request_id,
                                "approved": True,
                            },
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                            "type": "danger",
                            "value": {
                                "request_id": request.request_id,
                                "approved": False,
                            },
                        },
                    ],
                },
            ],
        }

        # 调用飞书发送卡片
        try:
            from src.mcp_tools.feishu import _get_feishu_token, _feishu_request
            token = _get_feishu_token()
            if not token:
                logger.warning("Cannot get Feishu token, notification skipped")
                return

            receive_id_type = getattr(settings, "alert_feishu_receive_id_type", "open_id")
            _feishu_request(
                method="POST",
                path="/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                body={
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": __import__("json").dumps(card_content),
                },
            )
            logger.info(
                "Feishu approval card sent: id=%s, receive_id=%s",
                request.request_id, receive_id,
            )
        except Exception as e:
            logger.warning("Failed to send Feishu card: %s", e)

    def _wait_for_approval(self, request: ApprovalRequest) -> ApprovalResult:
        """等待审批结果（轮询）

        生产环境建议改用：
            - Redis pub/sub
            - WebSocket 推送
            - 飞书事件回调
        """
        deadline = request.created_at + self.timeout
        poll_interval = 2  # 2 秒轮询一次

        while time.time() < deadline:
            if request.status != ApprovalStatus.PENDING:
                # 已审批
                approved = request.status == ApprovalStatus.APPROVED
                return ApprovalResult(
                    approved=approved,
                    status=request.status,
                    request_id=request.request_id,
                    reviewer_id=request.reviewer_id,
                    comment=request.review_comment,
                    message=f"审批{'通过' if approved else '拒绝'}: {request.review_comment}",
                )
            time.sleep(poll_interval)

        # 超时
        request.status = ApprovalStatus.TIMEOUT
        logger.warning(
            "Approval timeout: id=%s, action=%s, timeout=%ds",
            request.request_id, request.action, self.timeout,
        )
        return ApprovalResult(
            approved=False,
            status=ApprovalStatus.TIMEOUT,
            request_id=request.request_id,
            message=f"审批超时（{self.timeout}秒未响应），操作已拒绝",
        )


# 敏感操作列表（需要审批的操作）
SENSITIVE_ACTIONS = {
    "refund": "退款操作",
    "delete_account": "账户注销",
    "export_data": "数据导出",
    "modify_order": "订单修改",
    "large_refund": "大额退款（>1000元）",
    "reset_password": "密码重置",
    "change_permission": "权限变更",
}


def is_sensitive_action(action: str) -> bool:
    """判断操作是否为敏感操作（需要审批）"""
    return action in SENSITIVE_ACTIONS


# 全局单例
_humanloop_manager: Optional[HumanLoopManager] = None


def get_humanloop_manager() -> HumanLoopManager:
    """获取全局 HumanLoopManager 单例"""
    global _humanloop_manager
    if _humanloop_manager is None:
        _humanloop_manager = HumanLoopManager()
    return _humanloop_manager
