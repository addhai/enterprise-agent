"""流式输出引擎单元测试

覆盖 streaming.py：
- StreamingEngine._extract_text 多格式文本提取
- StreamingEngine.stream 流式生成（含缓冲、完成标记）
- WorkflowStreamer 节点级事件编排
"""
import pytest

from src.websocket.protocol import TYPE_STREAMING_CHUNK, TYPE_TYPING_INDICATOR
from src.websocket.streaming import StreamingEngine, WorkflowStreamer


# ============================================================
# _extract_text 文本提取
# ============================================================

class TestExtractText:
    def test_extract_from_object_with_content(self):
        class Chunk:
            content = "hello"
        assert StreamingEngine._extract_text(Chunk()) == "hello"

    def test_extract_from_object_with_empty_content(self):
        class Chunk:
            content = ""
        assert StreamingEngine._extract_text(Chunk()) == ""

    def test_extract_from_object_with_none_content(self):
        class Chunk:
            content = None
        assert StreamingEngine._extract_text(Chunk()) == ""

    def test_extract_from_dict_with_content_key(self):
        chunk = {"content": "dict content"}
        assert StreamingEngine._extract_text(chunk) == "dict content"

    def test_extract_from_dict_with_text_key(self):
        chunk = {"text": "dict text"}
        assert StreamingEngine._extract_text(chunk) == "dict text"

    def test_extract_from_string(self):
        assert StreamingEngine._extract_text("raw string") == "raw string"

    def test_extract_from_unsupported_type(self):
        assert StreamingEngine._extract_text(12345) == ""


# ============================================================
# StreamingEngine.stream
# ============================================================

class TestStreamingEngineStream:
    @pytest.mark.asyncio
    async def test_stream_produces_typing_and_chunks(self):
        """流式输出应先发 typing indicator，再发 chunks，最后发 done"""
        engine = StreamingEngine(chunk_size=2)

        async def mock_stream():
            for text in ["你好", "世界", "测试"]:
                yield {"content": text}

        events = []
        async for event in engine.stream(mock_stream(), "s1", "thinking"):
            events.append(event)

        # 应包含 typing indicator（开始）
        typing_events = [e for e in events if e["type"] == TYPE_TYPING_INDICATOR]
        assert len(typing_events) >= 2  # 至少开始和结束
        assert typing_events[0]["is_typing"] is True
        assert typing_events[-1]["is_typing"] is False

        # 应包含 streaming chunks
        chunk_events = [e for e in events if e["type"] == TYPE_STREAMING_CHUNK]
        assert len(chunk_events) >= 1
        # 最后一个 chunk 应标记 done
        assert chunk_events[-1]["done"] is True

    @pytest.mark.asyncio
    async def test_stream_buffers_by_chunk_size(self):
        """chunk_size=3 时应累积 3 个 token 再推送"""
        engine = StreamingEngine(chunk_size=3)

        async def mock_stream():
            for i in range(5):
                yield {"content": f"t{i}"}

        events = []
        async for event in engine.stream(mock_stream(), "s1"):
            events.append(event)

        chunk_events = [e for e in events if e["type"] == TYPE_STREAMING_CHUNK and e["text"]]
        # 5 个 token，chunk_size=3 → 第一次 3 个，第二次 2 个（剩余缓冲）
        assert len(chunk_events) == 2

    @pytest.mark.asyncio
    async def test_stream_handles_empty_generator(self):
        engine = StreamingEngine()

        async def mock_stream():
            return
            yield  # 让它成为 async generator

        events = []
        async for event in engine.stream(mock_stream(), "s1"):
            events.append(event)

        # 即使无内容，也应有 typing indicator 和 done chunk
        typing_events = [e for e in events if e["type"] == TYPE_TYPING_INDICATOR]
        chunk_events = [e for e in events if e["type"] == TYPE_STREAMING_CHUNK]
        assert len(typing_events) >= 1
        assert chunk_events[-1]["done"] is True

    @pytest.mark.asyncio
    async def test_stream_skips_empty_text(self):
        engine = StreamingEngine(chunk_size=1)

        async def mock_stream():
            yield {"content": ""}
            yield {"content": "real"}
            yield {"content": None}

        events = []
        async for event in engine.stream(mock_stream(), "s1"):
            events.append(event)

        chunk_events = [e for e in events if e["type"] == TYPE_STREAMING_CHUNK and e["text"]]
        assert len(chunk_events) == 1
        assert chunk_events[0]["text"] == "real"


# ============================================================
# WorkflowStreamer
# ============================================================

class TestWorkflowStreamer:
    @pytest.mark.asyncio
    async def test_emit_typing_for_known_node(self):
        """已知节点应推送对应的 typing indicator"""
        streamer = WorkflowStreamer("s1")
        await streamer.emit("entry")

        events = list(streamer.events())
        assert len(events) == 1
        assert events[0]["type"] == TYPE_TYPING_INDICATOR
        assert "正在加载" in events[0]["status"]

    @pytest.mark.asyncio
    async def test_emit_silent_for_reply_node(self):
        """reply 节点无 label，不应推送事件"""
        streamer = WorkflowStreamer("s1")
        await streamer.emit("reply")

        events = list(streamer.events())
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_emit_unknown_node_no_event(self):
        """未知节点不应推送事件"""
        streamer = WorkflowStreamer("s1")
        await streamer.emit("nonexistent_node")

        events = list(streamer.events())
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_emit_chunk_pushes_streaming_chunk(self):
        streamer = WorkflowStreamer("s1")
        await streamer.emit_chunk("hello", delta="hello", done=False)

        events = list(streamer.events())
        assert len(events) == 1
        assert events[0]["type"] == TYPE_STREAMING_CHUNK
        assert events[0]["text"] == "hello"

    @pytest.mark.asyncio
    async def test_emit_done_sets_finished_flag(self):
        streamer = WorkflowStreamer("s1")
        await streamer.emit_done()

        assert streamer._finished is True
        events = list(streamer.events())
        # emit_done 推送 typing off + done chunk
        assert len(events) >= 2

    @pytest.mark.asyncio
    async def test_node_labels_coverage(self):
        """NODE_LABELS 应覆盖核心工作流节点"""
        expected_nodes = {"entry", "clarify", "router", "faq", "rag", "reflect", "reply", "human"}
        assert expected_nodes.issubset(set(WorkflowStreamer.NODE_LABELS.keys()))
