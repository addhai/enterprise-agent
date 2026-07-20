"""
Agent Card 注册中心 — 统一目录服务

所有 Agent（客服、性能专家、安全专家、Orchestrator）在此注册其 Agent Card，
支持动态发现、查询和路由。

架构:
  ┌──────────────────────────────────────────┐
  │        Agent Registry (本服务)           │
  │  ┌────────────────────────────────────┐  │
  │  │  Registry Store (内存/持久化)       │  │
  │  │  - Customer Service Agent Card     │  │
  │  │  - Performance Expert Agent Card   │  │
  │  │  - Security Expert Agent Card      │  │
  │  │  - Orchestrator Agent Card         │  │
  │  └────────────────────────────────────┘  │
  └──────────────────────────────────────────┘
                    ▲
        ┌───────────┼───────────┐
        │           │           │
   客服 Agent   性能专家    安全专家    Orchestrator

使用方式:
  # 注册 Agent Card
  from src.protocols.agent_registry import register_agent_card, get_agent_card
  register_agent_card("customer_service", card)

  # 查询 Agent Card
  card = get_agent_card("performance_expert")

  # 发现所有可用 Agent
  agents = list_agents()

  # 按技能匹配 Agent
  matched = find_agents_by_skill("performance")
"""

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis 适配层（延迟初始化，连接失败自动降级为内存模式）
# ---------------------------------------------------------------------------

_redis_client: Optional[object] = None


def _get_redis():
    """延迟初始化 Redis 客户端（连接不可用时返回 None）

    复用 short_term.py 的模式：
    - 首次调用时创建连接
    - 连接失败返回 None（自动降级为纯内存）
    - 已连接时用 ping() 检查可用性
    """
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except Exception:
            logger.warning("AgentRegistry: Redis ping failed, falling back to in-memory")
            return None

    try:
        import redis as _redis_mod
        # protocol=2 兼容 Redis 3.x（旧版 Windows Redis 不支持 HELLO/RESP3）
        _redis_client = _redis_mod.from_url(
            settings.redis_url, decode_responses=True, protocol=2,
        )
        _redis_client.ping()
        logger.info("AgentRegistry: Redis connected (%s)", settings.redis_url)
        return _redis_client
    except Exception:
        logger.info("AgentRegistry: Redis unavailable, using in-memory only")
        return None


# Redis key 常量
REDIS_KEY_REGISTRY = "ea:agent_registry"  # Hash: field=agent_id, value=JSON(entry.to_dict())


class AgentCardEntry:
    """Agent Card 注册表条目"""

    def __init__(
        self,
        agent_id: str,
        name: str,
        description: str,
        url: str,
        skills: List[dict] = None,
        capabilities: dict = None,
        version: str = "1.0.0",
    ):
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.url = url
        self.skills = skills or []
        self.capabilities = capabilities or {}
        self.version = version
        self.registered_at = datetime.now(timezone.utc)
        self.last_heartbeat = datetime.now(timezone.utc)
        self.status = "online"

    def to_dict(self) -> dict:
        """转换为字典格式（用于 Redis 序列化）"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "skills": self.skills,
            "capabilities": self.capabilities,
            "version": self.version,
            "registered_at": self.registered_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentCardEntry":
        """从字典恢复（用于 Redis 反序列化）"""
        entry = cls(
            agent_id=data["agent_id"],
            name=data["name"],
            description=data["description"],
            url=data["url"],
            skills=data.get("skills", []),
            capabilities=data.get("capabilities", {}),
            version=data.get("version", "1.0.0"),
        )
        # 恢复时间字段
        if "registered_at" in data:
            entry.registered_at = datetime.fromisoformat(data["registered_at"])
        if "last_heartbeat" in data:
            entry.last_heartbeat = datetime.fromisoformat(data["last_heartbeat"])
        if "status" in data:
            entry.status = data["status"]
        return entry


class AgentRegistry:
    """Agent Card 注册中心 — 线程安全的单例服务"""

    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._registry: Dict[str, AgentCardEntry] = {}
                cls._instance._skill_index: Dict[str, List[str]] = {}
        return cls._instance

    # ---- Redis 持久化辅助方法 ----

    def _persist_to_redis(self, entry: AgentCardEntry):
        """将单条 Agent 写入 Redis（write-through）"""
        r = _get_redis()
        if r is None:
            return
        try:
            r.hset(
                REDIS_KEY_REGISTRY,
                entry.agent_id,
                json.dumps(entry.to_dict(), ensure_ascii=False),
            )
        except Exception as e:
            logger.warning("AgentRegistry: persist to Redis failed (%s): %s", entry.agent_id, e)

    def _remove_from_redis(self, agent_id: str):
        """从 Redis 删除单条 Agent"""
        r = _get_redis()
        if r is None:
            return
        try:
            r.hdel(REDIS_KEY_REGISTRY, agent_id)
        except Exception as e:
            logger.warning("AgentRegistry: remove from Redis failed (%s): %s", agent_id, e)

    def load_from_redis(self) -> int:
        """启动时从 Redis 加载所有 Agent 到内存（幂等，Redis 不可用时返回 0）

        Returns:
            从 Redis 加载的 Agent 数量
        """
        r = _get_redis()
        if r is None:
            return 0
        try:
            all_data = r.hgetall(REDIS_KEY_REGISTRY)
            if not all_data:
                return 0
            count = 0
            with self._lock:
                for agent_id, json_str in all_data.items():
                    try:
                        data = json.loads(json_str)
                        entry = AgentCardEntry.from_dict(data)
                        self._registry[agent_id] = entry
                        # 重建技能索引
                        for skill in entry.skills:
                            for tag in skill.get("tags", []):
                                tag_lower = tag.lower()
                                if tag_lower not in self._skill_index:
                                    self._skill_index[tag_lower] = []
                                if agent_id not in self._skill_index[tag_lower]:
                                    self._skill_index[tag_lower].append(agent_id)
                        count += 1
                    except Exception as e:
                        logger.warning(
                            "AgentRegistry: failed to restore agent %s from Redis: %s",
                            agent_id, e,
                        )
            if count > 0:
                logger.info("AgentRegistry: restored %d agents from Redis", count)
            return count
        except Exception as e:
            logger.warning("AgentRegistry: load from Redis failed: %s", e)
            return 0

    # ---- 业务方法 ----

    def register(
        self,
        agent_id: str,
        name: str,
        description: str,
        url: str,
        skills: List[dict] = None,
        capabilities: dict = None,
        version: str = "1.0.0",
    ) -> AgentCardEntry:
        """注册 Agent Card

        Args:
            agent_id: Agent 唯一标识（如 "customer_service", "performance_expert"）
            name: Agent 显示名称
            description: Agent 描述
            url: Agent 的 A2A/MCP 服务地址
            skills: Agent 技能列表（字典格式）
            capabilities: Agent 能力描述
            version: 版本号

        Returns:
            注册的条目
        """
        with self._lock:
            entry = AgentCardEntry(
                agent_id=agent_id,
                name=name,
                description=description,
                url=url,
                skills=skills or [],
                capabilities=capabilities or {},
                version=version,
            )
            self._registry[agent_id] = entry

            # 构建技能索引
            for skill in entry.skills:
                for tag in skill.get("tags", []):
                    tag_lower = tag.lower()
                    if tag_lower not in self._skill_index:
                        self._skill_index[tag_lower] = []
                    if agent_id not in self._skill_index[tag_lower]:
                        self._skill_index[tag_lower].append(agent_id)

            logger.info("Agent registered: %s (%s) at %s", agent_id, name, url)
            # write-through：同步写入 Redis
            self._persist_to_redis(entry)
            return entry

    def unregister(self, agent_id: str) -> bool:
        """注销 Agent"""
        with self._lock:
            if agent_id in self._registry:
                entry = self._registry.pop(agent_id)

                # 清理技能索引
                for skill in entry.skills:
                    for tag in skill.get("tags", []):
                        tag_lower = tag.lower()
                        if tag_lower in self._skill_index:
                            if agent_id in self._skill_index[tag_lower]:
                                self._skill_index[tag_lower].remove(agent_id)
                                if not self._skill_index[tag_lower]:
                                    del self._skill_index[tag_lower]

                logger.info("Agent unregistered: %s", agent_id)
                # 同步从 Redis 删除
                self._remove_from_redis(agent_id)
                return True
            return False

    def get(self, agent_id: str) -> Optional[AgentCardEntry]:
        """获取 Agent Card 条目"""
        with self._lock:
            return self._registry.get(agent_id)

    def list(self) -> List[AgentCardEntry]:
        """列出所有已注册的 Agent"""
        with self._lock:
            return list(self._registry.values())

    def list_online(self) -> List[AgentCardEntry]:
        """列出所有在线状态的 Agent"""
        with self._lock:
            return [e for e in self._registry.values() if e.status == "online"]

    def heartbeat(self, agent_id: str) -> bool:
        """更新 Agent 心跳，标记为在线"""
        with self._lock:
            entry = self._registry.get(agent_id)
            if entry:
                entry.last_heartbeat = datetime.now(timezone.utc)
                entry.status = "online"
                # write-through：心跳同步到 Redis
                self._persist_to_redis(entry)
                return True
            return False

    def mark_offline(self, agent_id: str) -> bool:
        """标记 Agent 为离线"""
        with self._lock:
            entry = self._registry.get(agent_id)
            if entry:
                entry.status = "offline"
                # write-through：离线状态同步到 Redis
                self._persist_to_redis(entry)
                return True
            return False

    def find_by_skill(self, keyword: str) -> List[AgentCardEntry]:
        """根据技能关键词查找匹配的 Agent

        Args:
            keyword: 技能关键词（如 "performance", "security", "billing"）

        Returns:
            匹配的 Agent 列表
        """
        with self._lock:
            keyword_lower = keyword.lower()
            matched_ids = set()

            # 按标签匹配
            if keyword_lower in self._skill_index:
                matched_ids.update(self._skill_index[keyword_lower])

            # 按技能名称/描述匹配
            for entry in self._registry.values():
                for skill in entry.skills:
                    skill_name = skill.get("name", "").lower()
                    skill_desc = skill.get("description", "").lower()
                    if keyword_lower in skill_name or keyword_lower in skill_desc:
                        matched_ids.add(entry.agent_id)

            # 按 Agent 名称/描述匹配
            for entry in self._registry.values():
                if (
                    keyword_lower in entry.name.lower()
                    or keyword_lower in entry.description.lower()
                ):
                    matched_ids.add(entry.agent_id)

            return [self._registry[aid] for aid in matched_ids if aid in self._registry]

    def find_by_capability(self, capability: str) -> List[AgentCardEntry]:
        """根据能力查找 Agent"""
        with self._lock:
            return [
                entry
                for entry in self._registry.values()
                if capability in entry.capabilities
            ]

    def get_stats(self) -> dict:
        """获取注册中心统计信息"""
        with self._lock:
            total = len(self._registry)
            online = sum(1 for e in self._registry.values() if e.status == "online")
            offline = total - online
            return {
                "total_agents": total,
                "online_agents": online,
                "offline_agents": offline,
                "total_skills": sum(len(e.skills) for e in self._registry.values()),
                "skill_tags": list(self._skill_index.keys()),
            }

    def clear(self):
        """清空注册表（测试用）"""
        with self._lock:
            self._registry.clear()
            self._skill_index.clear()


# 全局单例
registry = AgentRegistry()


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def register_agent_card(
    agent_id: str,
    name: str,
    description: str,
    url: str,
    skills: List[dict] = None,
    capabilities: dict = None,
    version: str = "1.0.0",
) -> AgentCardEntry:
    """便捷函数：注册 Agent Card"""
    return registry.register(
        agent_id=agent_id,
        name=name,
        description=description,
        url=url,
        skills=skills,
        capabilities=capabilities,
        version=version,
    )


def get_agent_card(agent_id: str) -> Optional[AgentCardEntry]:
    """便捷函数：获取 Agent Card"""
    return registry.get(agent_id)


def list_agents() -> List[AgentCardEntry]:
    """便捷函数：列出所有 Agent"""
    return registry.list()


def list_online_agents() -> List[AgentCardEntry]:
    """便捷函数：列出在线 Agent"""
    return registry.list_online()


def find_agents_by_skill(keyword: str) -> List[AgentCardEntry]:
    """便捷函数：按技能查找 Agent"""
    return registry.find_by_skill(keyword)


def get_registry_stats() -> dict:
    """便捷函数：获取注册中心统计"""
    return registry.get_stats()


def unregister_agent_card(agent_id: str) -> bool:
    """便捷函数：注销 Agent"""
    return registry.unregister(agent_id)


def heartbeat(agent_id: str) -> bool:
    """便捷函数：更新 Agent 心跳"""
    return registry.heartbeat(agent_id)


def mark_offline(agent_id: str) -> bool:
    """便捷函数：标记 Agent 为离线"""
    return registry.mark_offline(agent_id)


# ---------------------------------------------------------------------------
# 默认 Agent 注册（延迟加载）
# ---------------------------------------------------------------------------


def register_default_agents():
    """注册默认的内置 Agent

    启动时调用顺序：
    1. 先从 Redis 恢复之前持久化的动态注册 Agent
    2. 再注册代码中定义的默认 Agent（upsert，以代码为准）
    """
    from src.config import settings

    # 步骤 1：从 Redis 恢复已持久化的 Agent（动态注册的会被恢复）
    restored = registry.load_from_redis()
    if restored > 0:
        logger.info("Restored %d agents from Redis on startup", restored)

    # 性能专家 Agent
    from src.protocols.perf_agent import PERF_AGENT_SKILLS
    perf_url = settings.a2a_perf_expert_url or "http://localhost:9002"
    register_agent_card(
        agent_id="performance_expert",
        name="Performance Diagnosis Expert Agent",
        description=(
            "CloudSync 性能诊断专家 Agent。"
            "专精文件同步性能问题、API 延迟分析、数据库锁冲突排查、大文件传输瓶颈。"
        ),
        url=perf_url,
        skills=PERF_AGENT_SKILLS,
        capabilities={"streaming": True},
        version="1.0.0",
    )

    # 安全专家 Agent
    from src.protocols.security_agent import SECURITY_AGENT_SKILLS
    sec_url = settings.a2a_security_expert_url or "http://localhost:9003"
    register_agent_card(
        agent_id="security_expert",
        name="Security Audit Expert Agent",
        description=(
            "CloudSync 安全审计专家 Agent。"
            "专精账号安全、权限越权检测、API Key 泄露评估、合规审计报告生成。"
        ),
        url=sec_url,
        skills=SECURITY_AGENT_SKILLS,
        capabilities={"streaming": True},
        version="1.0.0",
    )

    # 客服 Agent
    from src.protocols.a2a_server import SERVICE_AGENT_SKILLS
    cs_url = "http://localhost:9001"
    register_agent_card(
        agent_id="customer_service",
        name="CloudSync Customer Service Agent",
        description=(
            "CloudSync SaaS 平台智能客服 Agent。"
            "处理产品咨询、技术排查、SSO 配置、API 使用、错误排查。"
            "超出知识库范围自动转人工或委托专家。"
        ),
        url=cs_url,
        skills=SERVICE_AGENT_SKILLS,
        capabilities={"streaming": True},
        version="1.0.0",
    )

    # Orchestrator Agent
    from src.protocols.orchestrator_agent import ORCHESTRATOR_AGENT_SKILLS
    orch_url = settings.a2a_orchestrator_url or "http://localhost:9000"
    register_agent_card(
        agent_id="orchestrator",
        name="Orchestrator Agent",
        description=(
            "CloudSync Orchestrator Agent — 多专家协调器。"
            "作为请求入口，智能路由用户请求到合适的专家 Agent（客服、性能、安全）。"
            "支持技能匹配路由、多专家协同、结果聚合、容错与降级。"
        ),
        url=orch_url,
        skills=ORCHESTRATOR_AGENT_SKILLS,
        capabilities={"streaming": True},
        version="1.0.0",
    )

    logger.info("Default agents registered to registry")
