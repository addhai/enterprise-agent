"""WebSocket 模块"""
from src.websocket.session_manager import (
    WebSocketSessionManager,
    SessionMode,
    SessionState,
    get_session_manager,
)
from src.websocket.dispatcher import (
    TransferDispatcher,
    TransferRecord,
    get_dispatcher,
)
from src.websocket.protocol import (
    TYPE_STREAMING_CHUNK,
    TYPE_TYPING_INDICATOR,
    TYPE_TRANSFER_NOTICE,
    TYPE_HANDOFF_CONTEXT,
    TYPE_NEW_TRANSFER,
    TYPE_COPILOT_SUGGESTION,
    TYPE_SESSION_UPDATE,
    TYPE_ERROR,
    build_streaming_chunk,
    build_typing_indicator,
    build_transfer_notice,
    build_handoff_context,
    build_new_transfer,
    build_copilot_suggestion,
    build_session_update,
    build_error,
)
from src.websocket.streaming import StreamingEngine, WorkflowStreamer
from src.websocket.handoff import build_handoff_context
from src.websocket.dispatcher import get_dispatcher

__all__ = [
    # Session Manager
    "WebSocketSessionManager",
    "SessionMode",
    "SessionState",
    "get_session_manager",
    # Dispatcher
    "TransferDispatcher",
    "TransferRecord",
    "get_dispatcher",
    # Streaming
    "StreamingEngine",
    "WorkflowStreamer",
    # Handoff
    "build_handoff_context",
    # Protocol
    "TYPE_STREAMING_CHUNK",
    "TYPE_TYPING_INDICATOR",
    "TYPE_TRANSFER_NOTICE",
    "TYPE_HANDOFF_CONTEXT",
    "TYPE_NEW_TRANSFER",
    "TYPE_COPILOT_SUGGESTION",
    "TYPE_SESSION_UPDATE",
    "TYPE_ERROR",
    "build_streaming_chunk",
    "build_typing_indicator",
    "build_transfer_notice",
    "build_handoff_context",
    "build_new_transfer",
    "build_copilot_suggestion",
    "build_session_update",
    "build_error",
]
