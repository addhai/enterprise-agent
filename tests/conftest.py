"""公共测试 fixtures —— 团队测试范式样板。

资深开发把关要点：
    1. 测试一律确定性：外部依赖（LLM / DB / Redis / HTTP）走注入或 mock，
       不依赖真实 API Key、不触网。CI 才能稳定、快速、可信。
    2. `asyncio_mode=auto` 已在 pyproject.toml 配置，异步测试无需手标。
"""

import os

import pytest

from src.agent.fake_llm import FakeLLMClient


@pytest.fixture(scope="session", autouse=True)
def _init_test_database():
    """为所有测试初始化一个独立的 SQLite 数据库（自动建表 + seed）。

    阶段一改造后，用户 / 知识库 / 工单 / 对话等 store 已落库；本 fixture 保证
    测试也能跑通，且使用独立的 test_agent.db，不污染开发用的 agent.db。
    """
    from src.config import settings

    settings.storage_backend = "sqlite"
    settings.database_url = "sqlite:///./test_agent.db"

    # 每次测试会话从干净状态开始
    try:
        os.remove("test_agent.db")
    except OSError:
        pass

    from src.db.init import init_db

    init_db()

    yield

    try:
        from src.db.engine import dispose_engine

        dispose_engine()
    except Exception:
        pass

# ---- 收集时忽略：这些目录的 conftest 会导入不存在的模块或需要真实服务，
#      必须在 pytest 发现阶段就跳过，否则 import 就崩了（exit code 4）。
#      用 collect_ignore（精确路径）而非 collect_ignore_glob（glob 模式），
#      因为后者对目录级 conftest.py 的拦截不够早。
collect_ignore = [
    "test_graph",
    "test_rag",
    "test_api",
    "test_memory",
    "test_protocols",
    "test_langchain",
    "security",
    "test_integrations",
    "test_websocket",
]


@pytest.fixture
def fake_llm_client():
    """返回一个确定性假 LLM：固定回复，不涉及任何外部调用。"""
    return FakeLLMClient(
        content="这是一段确定性的测试回复，包含关键词：密码重置。"
    )


@pytest.fixture
def fake_llm_error():
    """返回一个会抛出可重试错误的假 LLM，用于验证异常安全路径。"""
    return FakeLLMClient(
        content="",
        raise_on_invoke=RuntimeError("upstream 503 Service Unavailable"),
    )


@pytest.fixture
def make_agent():
    """工厂 fixture：用注入式假 LLM 构造 Agent，无需 API Key。

    用法：
        def test_xxx(make_agent):
            agent = make_agent(reply="你好，我是客服。")
            assert "客服" in agent.run("你好")
    """

    def _make(reply: str = "默认回复", raise_on_invoke=None):
        from src.agent.agent import CustomerServiceAgent

        client = FakeLLMClient(content=reply, raise_on_invoke=raise_on_invoke)
        return CustomerServiceAgent(
            user_id="test_user",
            tenant_id="test_tenant",
            llm_client=client,
        )

    return _make
