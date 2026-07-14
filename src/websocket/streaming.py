"""流式输出引擎

将 LangGraph DAG 的执行过程转化为流式 WebSocket 事件：
    typing_indicator → streaming_chunk × N → typing_indicator(False)

核心思路：
    1. 在 LangGraph 的每个节点执行前发送 typing indicator
    2. 在 LLM 流式输出时逐 chunk 推送
    3. 节点切换时更新 typing indicator 文本
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Dict, Optional

from src.websocket.protocol import (
    build_streaming_chunk,
    build_typing_indicator,
)

logger = logging.getLogger(__name__)


class StreamingEngine:
    """流式输出引擎

    用法：
        engine = StreamingEngine()
        async for event in engine.stream(llm_astream_generator):
            yield event
    """

    def __init__(self, chunk_size: int = 3):
        """
        Args:
            chunk_size: 每次推送的 token 数量（累积缓冲，减少推送频率）
        """
        self.chunk_size = chunk_size
        self._buffer = ""

    async def stream(
        self,
        llm_stream: AsyncGenerator,
        session_id: str,
        node_label: str = "thinking",
    ) -> AsyncGenerator[Dict, None]:
        """将 LLM 异步流转化为 WebSocket 事件

        Args:
            llm_stream: LLM 的 astream() 或 astream_events 生成器
            session_id: 当前会话 ID
            node_label: 当前执行的节点标签（用于 typing indicator）

        Yields:
            WebSocket 消息字典
        """
        # 1. 发送"正在思考"指示器
        yield build_typing_indicator(session_id, is_typing=True)
        yield build_typing_indicator(session_id, is_typing=True, status=node_label)

        # 2. 累积流式 token
        full_text = ""
        chunk_count = 0

        try:
            async for chunk in llm_stream:
                # 从 chunk 中提取文本
                text = self._extract_text(chunk)
                if not text:
                    continue

                full_text += text
                self._buffer += text
                chunk_count += 1

                # 累积到一定量再推送
                if chunk_count >= self.chunk_size:
                    yield build_streaming_chunk(
                        session_id,
                        text=self._buffer,
                        delta=text,
                    )
                    self._buffer = ""
                    chunk_count = 0

        except asyncio.CancelledError:
            logger.info("Streaming cancelled for session %s", session_id)
        except Exception as e:
            logger.error("Streaming error: %s", e)

        # 3. 推送剩余缓冲
        if self._buffer:
            yield build_streaming_chunk(
                session_id,
                text=self._buffer,
                delta=self._buffer,
            )
            self._buffer = ""

        # 4. 发送完成标记
        yield build_streaming_chunk(session_id, text="", done=True)

        # 5. 隐藏打字指示器
        yield build_typing_indicator(session_id, is_typing=False)

    @staticmethod
    def _extract_text(chunk: Any) -> str:
        """从各种 LLM chunk 格式中提取文本"""
        # LangChain ChatOpenAI astream 格式
        if hasattr(chunk, "content"):
            return chunk.content or ""
        # dict 格式
        if isinstance(chunk, dict):
            return chunk.get("content", "") or chunk.get("text", "") or ""
        # 字符串
        if isinstance(chunk, str):
            return chunk
        return ""


# ====================================================================
# 节点级流式编排
# ====================================================================

class WorkflowStreamer:
    """工作流流式编排器

    在 LangGraph DAG 执行过程中，按节点阶段推送事件：
        entry → typing: "正在加载您的信息..."
        clarify → typing: "正在理解您的问题..."
        router → typing: "正在分析问题类型..."
        faq → typing: "正在搜索常见问题..."
        rag → typing: "正在查阅技术文档..."
        reflect → typing: "正在复核答案..."
        reply → (静默推送最终回复)
    """

    NODE_LABELS = {
        "entry": "正在加载您的信息...",
        "clarify": "正在理解您的问题...",
        "router": "正在分析问题类型...",
        "faq": "正在搜索常见问题...",
        "rag": "正在查阅技术文档...",
        "reflect": "正在复核答案...",
        "reply": "",
        "human": "正在为您转接人工客服...",
    }

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.engine = StreamingEngine()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._finished = False

    async def push_event(self, event: Dict):
        """推送到内部队列"""
        await self._queue.put(event)

    async def emit(self, node_name: str):
        """发射节点事件"""
        label = self.NODE_LABELS.get(node_name, "")
        if label:
            await self.push_event(build_typing_indicator(
                self.session_id, is_typing=True, status=label,
            ))
            logger.debug("Node %s: typing '%s'", node_name, label)

    async def emit_chunk(self, text: str, delta: str = "", done: bool = False):
        """发射流式文本块"""
        await self.push_event(build_streaming_chunk(
            self.session_id, text=text, delta=delta, done=done,
        ))

    async def emit_done(self):
        """发射完成信号"""
        await self.push_event(build_typing_indicator(
            self.session_id, is_typing=False,
        ))
        await self.push_event(build_streaming_chunk(
            self.session_id, text="", done=True,
        ))
        self._finished = True

    def events(self) -> AsyncGenerator[Dict, None]:
        """产出所有事件的生成器"""
        while not self._finished or not self._queue.empty():
            try:
                event = self._queue.get_nowait()
                yield event
            except asyncio.QueueEmpty:
                break
