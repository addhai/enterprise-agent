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
    测试也能跑通，且使用独立的临时库，不污染开发用的 agent.db。

    ⚠️ 必须用「每会话唯一文件名」：Windows 上 SQLite 文件被连接池锁住时，
    `os.remove` 会静默失败，导致旧库残留、固定 session_id 串味、测试顺序相关
    地失败（单独跑过、整跑挂）。唯一文件名从源头杜绝该问题。
    """
    from src.config import settings

    # 用内存库（StaticPool）做测试：零文件、零锁、无残留，且天然隔离。
    settings.storage_backend = "sqlite"
    settings.database_url = "sqlite:///:memory:"

    # 防御性清理：先释放可能持有的引擎（避免旧连接池占用内存库）
    try:
        from src.db.engine import dispose_engine

        dispose_engine()
    except Exception:
        pass

    from src.db.init import init_db

    init_db()

    yield

    try:
        from src.db.engine import dispose_engine

        dispose_engine()
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def _isolate_chroma_dir(tmp_path_factory):
    """把 Chroma 持久化目录重定向到会话临时目录，与 SQLite 同等隔离。

    2026-10-09 起因：修复检索句子通道接线（生产单例开始传入
    collection_name）后，本地开发残留的 ./chroma_data 处于标准集合为空、
    knowledge_base_sentences 有 1014 条的脏状态，让离线 API 测试真实发出
    embedding HTTP 请求并 502。测试契约是确定性、不触网，任何机器上的
    历史数据都不应影响测试结果。
    """
    from src.config import settings

    tmp_chroma = tmp_path_factory.mktemp("chroma_test")
    original = settings.chroma_persist_dir
    settings.chroma_persist_dir = str(tmp_chroma)
    yield
    settings.chroma_persist_dir = original


# ---- 收集时忽略清单
# 历史：这里曾屏蔽 test_graph/test_rag/test_api/test_memory/test_protocols/
#      test_integrations/test_websocket 七个目录（另有 test_langchain、security 两个
#      早已不存在的残留项）。理由写的是"conftest 导入不存在的模块或需要真实服务"。
# 2026-08-08 逐目录体检结论：其中五个目录一直是全绿的，只是被一并埋掉；
#      test_api 的 66 errors 源于三个测试文件仍导入重构中已删除的 _init_default_admin；
#      test_graph 的失败源于 human_node 重构为 HITL 中断节点后测试未同步。
#      根因修复后全部通过，屏蔽清单不再需要。
# 仍需外部依赖的用例（真实 LLM / 外部服务）已由各自的 pytest.skip 或
# `integration` marker 自行处理，不应再靠目录级黑名单一刀切。
collect_ignore: list[str] = []


def _run_llm_tests() -> bool:
    """是否显式开启真实 LLM / Embedding 用例。

    默认关闭：CI（GitHub Actions 公开仓库）与任何干净环境都自动跳过，保证
    测试套件确定性、不触网、快速、可信。需要本地实跑 LLM 路径时，设置
    `RUN_LLM_TESTS=1` 并配置好 OPENAI_API_KEY / DASHSCOPE_API_KEY 即可。

    为什么不是「检测到环境变量里有 Key 才跑」：
        本机开发时 `.env` 会被 `load_dotenv()` 回填到环境，导致「以为有 Key
        就不跳过」，但实际 Key 可能已失效 / 属于别的提供方，调用仍 500/报错，
        制造「本地红、CI 红」的假象。一律改成显式 opt-in，行为可预测。
    """
    return os.environ.get("RUN_LLM_TESTS") == "1"


def pytest_collection_modifyitems(config, items):
    """未显式开启时，自动跳过需要真实 API 的用例（requires_llm marker）。

    这里替代了以往的目录级黑名单：黑名单会把同目录下确定性的用例一起埋掉，
    且不说明原因；marker 方案只精确跳过真正触网的用例，且 `RUN_LLM_TESTS=1`
    即恢复运行。
    """
    if _run_llm_tests():
        return
    skip_marker = pytest.mark.skip(
        reason=(
            "需要真实 LLM/Embedding 凭据，默认跳过；"
            "设置 RUN_LLM_TESTS=1 并配置 API Key 后运行"
        )
    )
    for item in items:
        if "requires_llm" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture
def fake_llm_client():
    """返回一个确定性假 LLM：固定回复，不涉及任何外部调用。"""
    return FakeLLMClient(content="这是一段确定性的测试回复，包含关键词：密码重置。")


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


# ---------------------------------------------------------------------------
# REST /chat 链路打桩
# ---------------------------------------------------------------------------
# 背景（2026-10-01）：
#     `POST /api/v1/chat` 会调 `src.api.routes.get_workflow()` 拿编译好的
#     LangGraph 工作流，再 `app.invoke(...)` 真正跑一遍 Agent 编排。工作流构建时
#     会初始化 LLM 客户端并向外发请求。测试环境无凭据时，这个请求会一直挂着
#     （出网被丢包，不返回错误），表现为 pytest 进程卡死、被外部超时工具 SIGTERM。
#
#     此前那些用例只能标 `requires_llm` 跳过，等于「接口测了但永远不跑」。
#     本 fixture 遵循项目既有的注入范式（同 `test_llm_rebuild_hot_reload.py` 中
#     `monkeypatch.setattr("src.api.routes.get_workflow", ...)` 的写法），
#     在 get_workflow 这一层把工作流换成确定性的假实现，
#     于是 chat 用例可以在无 Key 环境下真跑、真断言，无需触网。


class FakeWorkflow:
    """确定性的假工作流，替代 LangGraph 编译产物。

    只实现 routes.chat 用到的契约：`invoke(state, config=None) -> dict`。
    返回值覆盖 chat 处理函数会读取的字段（final_response / needs_human /
    suggest_human / access_filtered / intent / turn_count / quality_score）。

    `captured` 记录每次 invoke 收到的 state，供测试断言调用方是否正确传参
    （例如 effective_max_turns 是否跟随配置）。
    """

    def __init__(self, response: str = "这是一段确定性的测试回复。"):
        self.response = response
        self.calls: list = []

    def invoke(self, state, config=None):
        self.calls.append({"state": state, "config": config})
        return {
            "final_response": self.response,
            "needs_human": False,
            "suggest_human": False,
            "access_filtered": 0,
            "intent": "faq",
            "turn_count": 1,
            "quality_score": 0.9,
        }


@pytest.fixture
def fake_workflow(monkeypatch):
    """把 routes.chat 的工作流换成假实现，返回该假实例供断言。

    用法（P0-1 起 /chat 强制登录，需先登录拿 token）：
        def test_xxx(client, fake_workflow, admin_token):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "你好"},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200
            # 可断言调用方传了什么 state（身份取自 token，非请求体）
            assert fake_workflow.calls[0]["state"]["user_id"] == "<token 用户>"
    """
    wf = FakeWorkflow()
    monkeypatch.setattr("src.api.routes.get_workflow", lambda: wf)
    return wf


@pytest.fixture(autouse=True)
def _security_test_isolation(monkeypatch):
    """P0-6 安全策略的测试隔离。

    1. 套件默认关闭「默认密码强制改密」拦截：大量既有用例直接拿 seed
       admin token 调业务接口，强制拦截会把它们全部打成 403。
       需要验证拦截行为的用例自行 monkeypatch 重新打开。
    2. 每个用例前清空登录失败计数，防止跨用例累积触发账号锁定。
    """
    from src.api.login_guard import get_login_guard
    from src.config import settings

    monkeypatch.setattr(settings, "require_default_password_change", False)
    get_login_guard().reset()
    yield
    get_login_guard().reset()


@pytest.fixture(autouse=True)
def _patch_chat_workflow_by_default(monkeypatch, request):
    """默认给所有测试打上 chat 打桩，防止误触网导致套件卡死。

    为什么要 autouse：chat 接口被 4 个测试文件、十几处调用散点引用，
    逐处补 fixture 难免漏；漏一处就是一次「进程静默挂死」，代价极高。
    全局兜底后，任何忘记声明的用例也不会把整个测试套件拖死。

    需要真实工作流的用例（例如断言 chat 落库副作用）可显式声明
    `fake_workflow` 之外的方式，或给用例加 `no_chat_stub` 标记解耦：
        @pytest.mark.no_chat_stub
        def test_xxx(...): ...
    """
    if "no_chat_stub" in request.keywords:
        return
    monkeypatch.setattr("src.api.routes.get_workflow", lambda: FakeWorkflow())


def pytest_configure(config):
    """注册自定义 marker，避免 pytest 报 unknown marker 警告。"""
    config.addinivalue_line(
        "markers",
        "no_chat_stub: 不使用 tests/conftest.py 默认的 chat 工作流打桩，"
        "用于需要真实工作流的用例（如验证 chat 落库副作用）",
    )
