"""专家 Agent A2A 委托测试 — 性能诊断 + 安全审计"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ---------------------------------------------------------------------------
# 性能诊断专家 Agent 测试
# ---------------------------------------------------------------------------

class TestPerfExpertDiagnosis:
    """测试性能诊断专家的关键词匹配诊断逻辑"""

    def test_diagnose_sync_stuck(self):
        from src.protocols.perf_agent import _diagnose
        result = _diagnose("My sync is stuck at processing for 30 minutes")
        assert "同步卡住" in result
        assert "文件锁定" in result

    def test_diagnose_sync_stuck_chinese(self):
        from src.protocols.perf_agent import _diagnose
        result = _diagnose("我的同步卡住了，已经跑了7小时")
        assert "同步卡住" in result

    def test_diagnose_api_latency(self):
        from src.protocols.perf_agent import _diagnose
        result = _diagnose("Getting 429 rate limit errors frequently")
        assert "API 延迟" in result
        assert "指数退避" in result

    def test_diagnose_large_file(self):
        from src.protocols.perf_agent import _diagnose
        result = _diagnose("Uploading a 500GB file takes too long")
        assert "大文件传输" in result
        assert "分块" in result

    def test_diagnose_db_lock(self):
        from src.protocols.perf_agent import _diagnose
        result = _diagnose("Getting deadlock errors during bulk sync")
        assert "数据库锁" in result
        assert "死锁" in result

    def test_diagnose_generic_fallback(self):
        from src.protocols.perf_agent import _diagnose
        result = _diagnose("Something is weird with my account")
        assert "性能诊断" in result
        assert "系统资源" in result

    def test_diagnose_empty_query(self):
        from src.protocols.perf_agent import _diagnose
        result = _diagnose("")
        assert "性能诊断" in result


class TestPerfAgentSkills:
    """测试性能专家 Agent skills 元数据"""

    def test_perf_skills_count(self):
        from src.protocols.perf_agent import PERF_AGENT_SKILLS
        assert len(PERF_AGENT_SKILLS) == 4

    def test_perf_skills_ids(self):
        from src.protocols.perf_agent import PERF_AGENT_SKILLS
        skill_ids = [s["id"] for s in PERF_AGENT_SKILLS]
        assert "sync_stuck_diagnosis" in skill_ids
        assert "api_latency_analysis" in skill_ids
        assert "large_file_transfer" in skill_ids
        assert "db_lock_diagnosis" in skill_ids

    def test_perf_skills_have_examples(self):
        from src.protocols.perf_agent import PERF_AGENT_SKILLS
        for skill in PERF_AGENT_SKILLS:
            assert len(skill["examples"]) >= 1
            assert skill["tags"]


# ---------------------------------------------------------------------------
# 安全审计专家 Agent 测试
# ---------------------------------------------------------------------------

class TestSecurityExpertAnalysis:
    """测试安全审计专家的关键词匹配分析逻辑"""

    def test_analyze_suspicious_login(self):
        from src.protocols.security_agent import _security_analyze
        result = _security_analyze("I see a login from an unknown IP address")
        assert "可疑登录" in result
        assert "异地登录" in result

    def test_analyze_suspicious_login_chinese(self):
        from src.protocols.security_agent import _security_analyze
        result = _security_analyze("我的账号有异常登录")
        assert "可疑登录" in result

    def test_analyze_permission_escalation(self):
        from src.protocols.security_agent import _security_analyze
        result = _security_analyze("A user accessed unauthorized resources")
        assert "权限越权" in result
        assert "角色变更" in result

    def test_analyze_api_key_leak(self):
        from src.protocols.security_agent import _security_analyze
        result = _security_analyze("My API key was accidentally committed to GitHub")
        assert "API Key 泄露" in result
        assert "吊销" in result

    def test_analyze_compliance_audit(self):
        from src.protocols.security_agent import _security_analyze
        result = _security_analyze("I need a compliance audit report for SOC2")
        assert "合规审计" in result
        assert "操作记录" in result

    def test_analyze_generic_fallback(self):
        from src.protocols.security_agent import _security_analyze
        result = _security_analyze("Something weird happened")
        assert "安全审计" in result
        assert "PERMISSION_DENIED" in result

    def test_analyze_empty_query(self):
        from src.protocols.security_agent import _security_analyze
        result = _security_analyze("")
        assert "安全审计" in result


class TestSecurityAgentSkills:
    """测试安全专家 Agent skills 元数据"""

    def test_security_skills_count(self):
        from src.protocols.security_agent import SECURITY_AGENT_SKILLS
        assert len(SECURITY_AGENT_SKILLS) == 4

    def test_security_skills_ids(self):
        from src.protocols.security_agent import SECURITY_AGENT_SKILLS
        skill_ids = [s["id"] for s in SECURITY_AGENT_SKILLS]
        assert "suspicious_login_detection" in skill_ids
        assert "permission_escalation_check" in skill_ids
        assert "api_key_leak_assessment" in skill_ids
        assert "compliance_audit_report" in skill_ids

    def test_security_skills_have_examples(self):
        from src.protocols.security_agent import SECURITY_AGENT_SKILLS
        for skill in SECURITY_AGENT_SKILLS:
            assert len(skill["examples"]) >= 1
            assert skill["tags"]


# ---------------------------------------------------------------------------
# A2A 委托工具测试
# ---------------------------------------------------------------------------

class TestExpertDelegationTools:
    """测试 A2A 委托工具的创建和调用"""

    def test_create_expert_delegation_tools(self):
        from src.protocols.a2a_server import create_expert_delegation_tools
        tools = create_expert_delegation_tools()
        assert len(tools) == 2
        tool_names = [t.name for t in tools]
        assert "delegate_to_performance_expert" in tool_names
        assert "delegate_to_security_audit_expert" in tool_names

    def test_perf_delegation_tool_description(self):
        from src.protocols.a2a_server import create_expert_delegation_tools
        tools = create_expert_delegation_tools()
        perf_tool = [t for t in tools if "performance" in t.name][0]
        assert "性能" in perf_tool.description or "performance" in perf_tool.description.lower()

    def test_security_delegation_tool_description(self):
        from src.protocols.a2a_server import create_expert_delegation_tools
        tools = create_expert_delegation_tools()
        sec_tool = [t for t in tools if "security" in t.name][0]
        assert "安全" in sec_tool.description or "security" in sec_tool.description.lower()


class TestDelegateToPerfExpert:
    """测试委托给性能专家的异步函数"""

    def test_delegate_to_perf_expert_local_fallback(self):
        """a2a-sdk 不可用时回退到本地诊断逻辑"""
        from src.protocols.a2a_server import delegate_to_perf_expert
        result = asyncio.run(delegate_to_perf_expert("sync stuck for 30 minutes"))
        assert result is not None
        assert "同步卡住" in result

    def test_delegate_to_perf_expert_local_fallback_large_file(self):
        from src.protocols.a2a_server import delegate_to_perf_expert
        result = asyncio.run(delegate_to_perf_expert("500GB file upload too slow"))
        assert result is not None
        assert "大文件" in result


class TestDelegateToSecurityExpert:
    """测试委托给安全专家的异步函数"""

    def test_delegate_to_security_expert_local_fallback(self):
        """a2a-sdk 不可用时回退到本地分析逻辑"""
        from src.protocols.a2a_server import delegate_to_security_expert
        result = asyncio.run(delegate_to_security_expert("API key leaked on GitHub"))
        assert result is not None
        assert "API Key 泄露" in result

    def test_delegate_to_security_expert_local_fallback_login(self):
        from src.protocols.a2a_server import delegate_to_security_expert
        result = asyncio.run(delegate_to_security_expert("suspicious login from unknown IP"))
        assert result is not None
        assert "可疑登录" in result


class TestLangChainToolIntegration:
    """测试 LangChain 工具封装的调用"""

    def test_perf_tool_returns_expert_result(self):
        from src.protocols.a2a_server import delegate_to_performance_expert
        result = delegate_to_performance_expert.invoke({"query": "sync stuck"})
        assert "性能专家诊断结果" in result
        assert "同步卡住" in result

    def test_perf_tool_returns_large_file_result(self):
        from src.protocols.a2a_server import delegate_to_performance_expert
        result = delegate_to_performance_expert.invoke({"query": "500GB file too slow"})
        assert "性能专家诊断结果" in result
        assert "大文件" in result

    def test_security_tool_returns_expert_result(self):
        from src.protocols.a2a_server import delegate_to_security_audit_expert
        result = delegate_to_security_audit_expert.invoke({"query": "API key leaked"})
        assert "安全专家分析结果" in result
        assert "API Key 泄露" in result

    def test_security_tool_returns_login_result(self):
        from src.protocols.a2a_server import delegate_to_security_audit_expert
        result = delegate_to_security_audit_expert.invoke({"query": "unknown IP login"})
        assert "安全专家分析结果" in result
        assert "可疑登录" in result


# ---------------------------------------------------------------------------
# 客服 Agent 工具集成测试
# ---------------------------------------------------------------------------

class TestAgentToolIntegration:
    """测试专家委托工具是否正确集成到客服 Agent 工具列表"""

    def test_create_tools_includes_delegation(self):
        from src.agent.tools import create_tools
        tools = create_tools(user_id="test_user")
        tool_names = [t.name for t in tools]
        assert "delegate_to_performance_expert" in tool_names
        assert "delegate_to_security_audit_expert" in tool_names
        # 原有工具仍然存在
        assert "search_knowledge_base" in tool_names
        assert "search_faq" in tool_names
        assert "escalate_to_human" in tool_names

    def test_create_tools_total_count(self):
        from src.agent.tools import create_tools
        tools = create_tools(user_id="test_user")
        # 3 原有 + 2 专家委托 + 2 外部 MCP 消费 = 7
        assert len(tools) == 7


# ---------------------------------------------------------------------------
# 配置测试
# ---------------------------------------------------------------------------

class TestExpertAgentConfig:
    """测试专家 Agent 配置"""

    def test_perf_expert_url_config(self):
        from src.config import settings
        assert settings.a2a_perf_expert_url == "http://localhost:9002"

    def test_security_expert_url_config(self):
        from src.config import settings
        assert settings.a2a_security_expert_url == "http://localhost:9003"

    def test_expert_timeout_config(self):
        from src.config import settings
        assert settings.a2a_expert_timeout == 30

    def test_perf_expert_enabled(self):
        from src.config import settings
        assert settings.a2a_perf_expert_enabled is True

    def test_security_expert_enabled(self):
        from src.config import settings
        assert settings.a2a_security_expert_enabled is True
