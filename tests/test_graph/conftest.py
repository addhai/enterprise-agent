"""graph 测试公共 fixtures

重置单例状态，确保测试之间互不影响。
"""
import pytest

from src.graph import guardrails as guardrails_mod
from src.graph import hitl_manager as hitl_mod
from src.graph import workflow_dag as dag_mod


@pytest.fixture(autouse=True)
def reset_singletons(monkeypatch):
    """每个测试前后重置 graph 模块单例与全局存储"""
    # 重置 GuardrailAgent 单例
    guardrails_mod._guardrail_agent = None

    # 重置 HITLManager 单例
    hitl_mod._hitl_manager = None

    # 清空 workflow 全局存储
    dag_mod._workflow_store._store.clear()
    dag_mod._workflow_store._timestamps.clear()

    yield

    # 测试后再次清理
    guardrails_mod._guardrail_agent = None
    hitl_mod._hitl_manager = None
    dag_mod._workflow_store._store.clear()
    dag_mod._workflow_store._timestamps.clear()


@pytest.fixture(autouse=True)
def disable_redis_for_hitl(monkeypatch):
    """禁用 HITLManager 的 Redis（强制内存模式）"""
    monkeypatch.setattr("src.graph.hitl_manager._get_redis", lambda: None)
