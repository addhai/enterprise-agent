"""微信公众号/小程序接入层

职责：
    接收微信公众号/小程序的回调消息，转换为内部标准格式，
    通过调度中枢路由到对应的 Agent 子图处理。

支持的渠道：
    - 微信公众号：文本/图片/语音/菜单事件
    - 微信小程序：订阅消息/客服消息

安全验证：
    - 微信服务器签名验证（SHA1）
    - Token 匹配
    - EncodingAESKey 解密（可选）

消息格式转换：
    微信原始消息 → MessageNormalizer → NormalizedMessage → 调度中枢 → Agent
"""
from __future__ import annotations

import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

from src.dispatch.normalizer import get_message_normalizer
from src.websocket.session_manager import (
    SessionMode,
    get_session_manager,
)

logger = logging.getLogger(__name__)

# 微信公众号配置（从 settings 加载，支持环境变量覆盖）
from src.config import settings

WECHAT_TOKEN = settings.wechat_token if hasattr(settings, 'wechat_token') else ""
WECHAT_ENCODING_AES_KEY = settings.wechat_encoding_aes_key if hasattr(settings, 'wechat_encoding_aes_key') else ""
WECHAT_APP_ID = settings.wechat_app_id if hasattr(settings, 'wechat_app_id') else ""
WECHAT_APP_SECRET = settings.wechat_app_secret if hasattr(settings, 'wechat_app_secret') else ""


router = APIRouter(tags=["wechat"])


# ====================================================================
# 微信消息签名验证
# ====================================================================

def verify_wechat_signature(token: str, timestamp: str, nonce: str, signature: str) -> bool:
    """验证微信服务器请求签名

    算法：将 token、timestamp、nonce 三个参数字典序拼接后 SHA1 哈希，
    与 signature 比较。
    """
    sorted_params = sorted([token, timestamp, nonce])
    combined = "".join(sorted_params)
    computed = hashlib.sha1(combined.encode()).hexdigest()
    return computed == signature


# ====================================================================
# 微信回调端点
# ====================================================================

@router.get("/wechat/callback")
async def wechat_verify_endpoint(request: Request):
    """微信服务器 URL 验证（首次配置公众号时调用）"""
    params = request.query_params
    signature = params.get("signature", "")
    timestamp = params.get("timestamp", "")
    nonce = params.get("nonce", "")
    echostr = params.get("echostr", "")

    if not verify_wechat_signature(WECHAT_TOKEN, timestamp, nonce, signature):
        logger.warning("WeChat signature verification failed")
        return {"error": "signature mismatch"}

    logger.info("WeChat URL verified successfully")
    return echostr


@router.post("/wechat/callback")
async def wechat_callback(request: Request):
    """微信公众号消息回调入口

    接收微信服务器推送的 XML 消息，解析后通过调度中枢处理。
    """
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="replace")

    # 解析 XML
    try:
        root = ET.fromstring(raw_text)
    except ET.ParseError as e:
        logger.warning("Failed to parse WeChat XML: %s", e)
        return {"error": "invalid xml"}

    msg_type = root.find("MsgType")
    content_elem = root.find("Content")
    from_user = root.find("FromUserName")
    to_user = root.find("ToUserName")

    if msg_type is None or from_user is None:
        return {"error": "missing fields"}

    msg_type_val = msg_type.text or ""
    from_openid = from_user.text or ""

    # 1. 处理事件推送（关注/菜单点击）
    if msg_type_val == "event":
        event = root.find("Event")
        event_val = event.text if event is not None else ""
        if event_val == "subscribe":
            # 用户关注公众号，发送欢迎语
            welcome_msg = "欢迎关注 CloudSync 智能客服！请输入您的问题，我将为您解答。回复 '人工' 可转接人工客服。"
            return _build_response_xml(from_openid, to_user.text or "", welcome_msg)
        elif event_val == "CLICK":
            # 菜单点击事件
            event_key = root.find("EventKey")
            key_val = event_key.text if event_key is not None else ""
            return _handle_menu_click(from_openid, key_val)

    # 2. 处理文本消息
    if msg_type_val == "text":
        content = content_elem.text if content_elem is not None else ""
        if not content:
            return _build_response_xml(from_openid, to_user.text or "", "请输入您的问题。")

        # 归一化消息
        normalizer = get_message_normalizer()
        normalized = normalizer.normalize(
            raw_payload={
                "openid": from_openid,
                "msgtype": "text",
                "text": {"content": content},
            },
            channel="wechat_mp",
        )

        # 获取会话管理器
        session_mgr = get_session_manager()
        session_id = normalized.session_id
        state = session_mgr.get_session(session_id)
        if not state:
            session_mgr.create_session(
                session_id=session_id,
                user_id=normalized.user_id,
                tenant_id=normalized.tenant_id,
                mode=SessionMode.AI_CHAT,
            )

        # 调用工作流处理（简化版：直接返回 AI 回复）
        # 实际项目中应通过 WebSocket 异步推送回复
        reply_text = await _process_wechat_message(normalized, session_mgr)
        return _build_response_xml(from_openid, to_user.text or "", reply_text)

    # 3. 处理图片/语音消息（需要 OCR/ASR 转换）
    if msg_type_val in ("image", "voice"):
        return _build_response_xml(
            from_openid, to_user.text or "",
            "暂不支持图片/语音消息，请改用文字描述您的问题。"
        )

    return _build_response_xml(from_openid, to_user.text or "", "")


def _build_response_xml(from_user: str, to_user: str, content: str) -> Dict[str, Any]:
    """构建微信回复 XML"""
    timestamp = int(time.time())
    xml_template = """<xml>
<ToUserName><![CDATA[{to}]]></ToUserName>
<FromUserName><![CDATA[{from}]]></FromUserName>
<CreateTime>{time}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""
    return {
        "content": xml_template.format(
            to=to_user,
            from_=from_user,
            time=timestamp,
            content=content,
        ),
        "media_type": "text",
    }


def _handle_menu_click(openid: str, event_key: str) -> Dict[str, Any]:
    """处理菜单点击事件"""
    menu_responses = {
        "MENU_PRICING": "我们的定价方案：\n• 免费版：5GB 存储，2 个提供商\n• 专业版：$15/月，100GB 存储\n• 企业版：定制报价，无限存储",
        "MENU_ORDER": "请登录小程序后点击'我的订单'查看订单状态。如需帮助，请回复订单号。",
        "MENU_HUMAN": "正在为您转接人工客服，请稍候...",
    }
    content = menu_responses.get(event_key, "请问有什么可以帮助您的？")
    return _build_response_xml(openid, openid, content)


async def _process_wechat_message(
    normalized,
    session_mgr,
) -> str:
    """处理微信消息 → 调用 Agent 工作流 → 返回回复"""
    from src.graph.state import AgentState
    from langchain_core.messages import HumanMessage
    from src.api.dependencies import get_workflow

    app = get_workflow()
    session_id = normalized.session_id
    user_id = normalized.user_id

    state = AgentState(
        messages=[HumanMessage(content=normalized.content)],
        intent=None,
        retrieved_docs=[],
        needs_human=False,
        turn_count=0,
        final_response="",
        user_id=user_id,
        session_id=session_id,
        tenant_id=normalized.tenant_id,
        user_access_levels=["public", "internal", "confidential", "restricted"],
        user_roles=[],
        user_plan="free",  # 可从 CRM 获取
        faq_match=None,
        effective_max_turns=5,
        has_reflected=False,
        memory_context="",
        quality_score=None,
        access_filtered=0,
        needs_expert_delegation=False,
        expert_response=None,
    )

    try:
        result = app.invoke(state, config={"configurable": {"thread_id": session_id}})
        return result.get("final_response", "抱歉，处理您的消息时出错。")
    except Exception as e:
        logger.exception("WeChat message processing failed: %s", e)
        return "抱歉，服务暂时不可用。请稍后重试或转人工客服。"
