"""
测试 Orchestrator Agent 和 Agent Registry
"""

import pytest


class TestAgentRegistry:
    """Agent Registry 注册中心测试"""

    def setup_method(self):
        from src.protocols.agent_registry import registry
        registry.clear()

    def test_registry_singleton(self):
        """测试注册中心单例模式"""
        from src.protocols.agent_registry import AgentRegistry
        r1 = AgentRegistry()
        r2 = AgentRegistry()
        assert r1 is r2

    def test_register_agent(self):
        """测试注册 Agent"""
        from src.protocols.agent_registry import register_agent_card, get_agent_card

        register_agent_card(
            agent_id="test_agent",
            name="Test Agent",
            description="Test description",
            url="http://localhost:9090",
            skills=[{"id": "test_skill", "name": "Test Skill", "description": "Test", "tags": ["test"]}],
        )

        entry = get_agent_card("test_agent")
        assert entry is not None
        assert entry.agent_id == "test_agent"
        assert entry.name == "Test Agent"
        assert entry.url == "http://localhost:9090"
        assert len(entry.skills) == 1

    def test_unregister_agent(self):
        """测试注销 Agent"""
        from src.protocols.agent_registry import register_agent_card, unregister_agent_card, get_agent_card

        register_agent_card(
            agent_id="test_agent",
            name="Test Agent",
            description="Test",
            url="http://localhost:9090",
        )

        assert unregister_agent_card("test_agent") is True
        assert get_agent_card("test_agent") is None
        assert unregister_agent_card("nonexistent") is False

    def test_list_agents(self):
        """测试列出所有 Agent"""
        from src.protocols.agent_registry import register_agent_card, list_agents

        register_agent_card("agent1", "Agent 1", "Desc 1", "http://localhost:9091")
        register_agent_card("agent2", "Agent 2", "Desc 2", "http://localhost:9092")

        agents = list_agents()
        assert len(agents) == 2
        agent_ids = [a.agent_id for a in agents]
        assert "agent1" in agent_ids
        assert "agent2" in agent_ids

    def test_find_by_skill(self):
        """测试按技能查找 Agent"""
        from src.protocols.agent_registry import register_agent_card, find_agents_by_skill

        register_agent_card(
            agent_id="perf_agent",
            name="Performance Agent",
            description="Performance",
            url="http://localhost:9002",
            skills=[
                {"id": "skill1", "name": "Sync Diagnosis", "description": "Sync issues", "tags": ["performance", "sync"]},
            ],
        )

        register_agent_card(
            agent_id="sec_agent",
            name="Security Agent",
            description="Security",
            url="http://localhost:9003",
            skills=[
                {"id": "skill2", "name": "Auth Audit", "description": "Auth issues", "tags": ["security", "auth"]},
            ],
        )

        perf_agents = find_agents_by_skill("performance")
        assert len(perf_agents) == 1
        assert perf_agents[0].agent_id == "perf_agent"

        sec_agents = find_agents_by_skill("security")
        assert len(sec_agents) == 1
        assert sec_agents[0].agent_id == "sec_agent"

        sync_agents = find_agents_by_skill("sync")
        assert len(sync_agents) == 1

    def test_heartbeat(self):
        """测试心跳更新"""
        from src.protocols.agent_registry import register_agent_card, heartbeat, mark_offline, get_agent_card

        register_agent_card("test_agent", "Test", "Test", "http://localhost:9090")
        entry = get_agent_card("test_agent")

        assert entry.status == "online"
        old_heartbeat = entry.last_heartbeat

        assert heartbeat("test_agent") is True
        entry = get_agent_card("test_agent")
        assert entry.last_heartbeat > old_heartbeat

        assert heartbeat("nonexistent") is False

        assert mark_offline("test_agent") is True
        entry = get_agent_card("test_agent")
        assert entry.status == "offline"

    def test_get_stats(self):
        """测试统计信息"""
        from src.protocols.agent_registry import register_agent_card, get_registry_stats

        register_agent_card("agent1", "Agent 1", "Desc 1", "http://localhost:9091")
        register_agent_card(
            "agent2", "Agent 2", "Desc 2", "http://localhost:9092",
            skills=[{"id": "s1", "name": "Skill 1", "description": "Test", "tags": ["tag1", "tag2"]}],
        )

        stats = get_registry_stats()
        assert stats["total_agents"] == 2
        assert stats["online_agents"] == 2
        assert stats["offline_agents"] == 0
        assert stats["total_skills"] == 1
        assert "tag1" in stats["skill_tags"]
        assert "tag2" in stats["skill_tags"]

    def test_register_default_agents(self):
        """测试注册默认 Agent"""
        from src.protocols.agent_registry import register_default_agents, get_agent_card, list_agents

        register_default_agents()

        agents = list_agents()
        assert len(agents) >= 4

        assert get_agent_card("customer_service") is not None
        assert get_agent_card("performance_expert") is not None
        assert get_agent_card("security_expert") is not None
        assert get_agent_card("orchestrator") is not None


class TestOrchestratorRouting:
    """Orchestrator 路由逻辑测试"""

    def setup_method(self):
        from src.protocols.agent_registry import registry
        registry.clear()
        from src.protocols.agent_registry import register_default_agents
        register_default_agents()

    def test_route_performance_query(self):
        """测试性能问题路由"""
        from src.protocols.orchestrator_agent import Orchestrator

        orchestrator = Orchestrator()
        routing = asyncio.run(orchestrator.route_request("My sync is stuck and very slow"))

        assert routing["best_match"] == "performance_expert"
        matched_ids = [a["agent_id"] for a in routing["matched_agents"]]
        assert "performance_expert" in matched_ids

    def test_route_security_query(self):
        """测试安全问题路由"""
        from src.protocols.orchestrator_agent import Orchestrator

        orchestrator = Orchestrator()
        routing = asyncio.run(orchestrator.route_request("My API key may have been leaked"))

        assert routing["best_match"] == "security_expert"
        matched_ids = [a["agent_id"] for a in routing["matched_agents"]]
        assert "security_expert" in matched_ids

    def test_route_cs_query(self):
        """测试客服问题路由"""
        from src.protocols.orchestrator_agent import Orchestrator

        orchestrator = Orchestrator()
        routing = asyncio.run(orchestrator.route_request("How do I set up SSO?"))

        assert routing["best_match"] == "customer_service"
        matched_ids = [a["agent_id"] for a in routing["matched_agents"]]
        assert "customer_service" in matched_ids

    def test_route_mixed_query(self):
        """测试混合问题路由（性能 + 安全）"""
        from src.protocols.orchestrator_agent import Orchestrator

        orchestrator = Orchestrator()
        routing = asyncio.run(orchestrator.route_request("Slow sync and security concerns"))

        matched_ids = [a["agent_id"] for a in routing["matched_agents"]]
        assert "performance_expert" in matched_ids or "security_expert" in matched_ids

    def test_route_no_match(self):
        """测试无匹配的查询"""
        from src.protocols.orchestrator_agent import Orchestrator

        orchestrator = Orchestrator()
        routing = asyncio.run(orchestrator.route_request("Random query with no keywords"))

        assert routing["matched_agents"]
        assert "customer_service" in [a["agent_id"] for a in routing["matched_agents"]]

    def test_delegate_to_offline_agent(self):
        """测试委托到离线 Agent"""
        from src.protocols.orchestrator_agent import Orchestrator
        from src.protocols.agent_registry import mark_offline

        mark_offline("performance_expert")

        orchestrator = Orchestrator()
        result = asyncio.run(orchestrator.delegate_to_agent("performance_expert", "test"))

        assert result is None


class TestOrchestratorFullFlow:
    """Orchestrator 完整流程测试"""

    def setup_method(self):
        from src.protocols.agent_registry import registry
        registry.clear()
        from src.protocols.agent_registry import register_default_agents
        register_default_agents()

    def test_orchestrate_performance(self):
        """测试编排性能查询"""
        from src.protocols.orchestrator_agent import Orchestrator

        orchestrator = Orchestrator()
        result = asyncio.run(orchestrator.orchestrate("API responses are very slow"))

        assert result["query"] == "API responses are very slow"
        assert result["routing"]["best_match"] == "performance_expert"

    def test_orchestrate_security(self):
        """测试编排安全查询"""
        from src.protocols.orchestrator_agent import Orchestrator

        orchestrator = Orchestrator()
        result = asyncio.run(orchestrator.orchestrate("Security audit needed"))

        assert result["query"] == "Security audit needed"
        assert result["routing"]["best_match"] == "security_expert"

    def test_orchestrate_cs(self):
        """测试编排客服查询"""
        from src.protocols.orchestrator_agent import Orchestrator

        orchestrator = Orchestrator()
        result = asyncio.run(orchestrator.orchestrate("How to install?"))

        assert result["query"] == "How to install?"
        assert result["routing"]["best_match"] == "customer_service"


import asyncio
