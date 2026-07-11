"""电话 IVR 接入层

职责：
    接收电话 IVR 系统的语音消息，通过 ASR 转为文字，
    交给 Agent 处理后将回复通过 TTS 转为语音播放。

架构：
    用户说话 → IVR 系统 → ASR 转文字 → MessageNormalizer → Agent → TTS → IVR → 用户听到回复

支持的集成方式：
    1. Twilio API：美国/全球市场
    2. 阿里云语音：国内市场
    3. 腾讯云语音：国内市场
    4. 自建 SIP 服务器：私有部署

当前实现：Twilio 示例（可替换为其他供应商）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

from src.dispatch.normalizer import get_message_normalizer
from src.websocket.session_manager import (
    SessionMode,
    get_session_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["phone"])

# Twilio 配置（实际从环境变量读取）
import os
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "")


@router.post("/phone/inbound")
async def phone_inbound(request: Request):
    """接收电话来电（Twilio Webhook）

    Twilio 拨打此端点获取 TwiML 响应，指导 IVR 行为。
    """
    form_data = await request.form()
    from_number = form_data.get("From", "")  # 来电号码
    to_number = form_data.get("To", "")      # 接听号码
    call_sid = form_data.get("CallSid", "")  # 通话 ID

    logger.info("Incoming call: from=%s, to=%s, call_sid=%s", from_number, to_number, call_sid)

    # 返回 TwiML：播放欢迎语，然后等待用户说话
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">您好，欢迎致电 CloudSync 智能客服。请说出您的问题。</Say>
    <Gather input="speech" action="/phone/transcribe" timeout="5" numDigits="1"/>
    <Say voice="alice">未检测到语音输入，感谢您的来电。</Say>
</Response>"""

    return {"content": twiml, "media_type": "xml", "content_type": "application/xml"}


@router.post("/phone/transcribe")
async def phone_transcribe(request: Request):
    """处理 ASR 转录结果

    Twilio Gather 检测到语音后回调此端点。
    """
    form_data = await request.form()
    speech_result = form_data.get("SpeechResults", "")
    from_number = form_data.get("From", "")
    call_sid = form_data.get("CallSid", "")

    if not speech_result:
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">未听清，请再说一遍。</Say>
    <Gather input="speech" action="/phone/transcribe" timeout="5"/>
</Response>"""
        return {"content": twiml, "media_type": "xml", "content_type": "application/xml"}

    # 归一化消息
    normalizer = get_message_normalizer()
    normalized = normalizer.normalize(
        raw_payload={
            "phone": from_number,
            "asr_text": speech_result,
            "asr_confidence": 0.9,  # 实际从 SpeechResults 获取
        },
        channel="phone_ivr",
    )

    # 处理消息
    session_mgr = get_session_manager()
    reply = await _process_phone_message(normalized, session_mgr, call_sid)

    # 构建 TTS 回复 TwiML
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{reply[:200]}</Say>
    <Gather input="speech" action="/phone/transcribe" timeout="5"/>
</Response>"""

    return {"content": twiml, "media_type": "xml", "content_type": "application/xml"}


async def _process_phone_message(normalized, session_mgr, call_sid: str) -> str:
    """处理电话消息 → 调用 Agent → 返回 TTS 文本"""
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
        user_access_levels=["public", "internal"],
        user_roles=[],
        user_plan="free",
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
        reply = result.get("final_response", "抱歉，处理您的消息时出错。")
        # 电话回复需要简化（去除 Markdown/特殊字符）
        return _clean_for_tts(reply)
    except Exception as e:
        logger.exception("Phone message processing failed: %s", e)
        return "抱歉，服务暂时不可用。请稍后重试。"


def _clean_for_tts(text: str) -> str:
    """清理文本，使其适合 TTS 朗读"""
    # 去除 Markdown 符号
    import re
    text = re.sub(r'[#*_`]', '', text)
    # 去除方括号内容
    text = re.sub(r'\[.*?\]', '', text)
    # 替换特殊符号为自然语言
    text = text.replace('→', '然后').replace('✓', '正确').replace('✗', '错误')
    return text
