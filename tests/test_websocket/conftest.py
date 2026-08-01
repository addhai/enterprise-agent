"""WebSocket 测试公共 fixtures

重置单例状态，确保测试之间互不影响。
"""
import pytest

from src.websocket.session_manager import get_session_manager
from src.websocket.dispatcher import get_dispatcher


@pytest.fixture(autouse=True)
def reset_singletons():
    """每个测试前后重置 WebSocket 单例（SessionManager / Dispatcher）的内部状态"""
    mgr = get_session_manager()
    disp = get_dispatcher()

    # 测试前清空
    mgr._sessions.clear()
    mgr._agents.clear()
    disp._queue.clear()
    disp._records.clear()
    disp._session_transfers.clear()

    yield

    # 测试后清空
    mgr._sessions.clear()
    mgr._agents.clear()
    disp._queue.clear()
    disp._records.clear()
    disp._session_transfers.clear()
