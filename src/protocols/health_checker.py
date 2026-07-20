"""
Agent 健康检查 — 心跳超时扫描 + 主动探活 + 熔断器 + 飞书告警

依赖 src.protocols.agent_registry 的注册中心。
启动后会在后台定期扫描所有 Agent 的 last_heartbeat，超时则标记 offline；
可选地对在线 Agent 发起 HTTP /health 探测，双重保险。
Agent 从 online→offline 时自动发送飞书告警（可在 config 开关），
从 offline→online 恢复时发送恢复通知。

熔断器（CircuitBreaker）记录每个 Agent 的调用失败次数，
连续失败超阈值时进入"断开"状态，路由前可调用 can_call() 拒绝调用，
避免反复把请求扔给故障 Agent。

接入方式（server.py 的 startup/shutdown）：
    from src.protocols.health_checker import get_health_checker
    checker = get_health_checker()
    await checker.start()
    # ...
    await checker.stop()
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

# 尝试导入 httpx（探活用）；缺失时关闭主动探活
try:
    import httpx  # noqa: F401
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

# 尝试导入 metrics（生产环境用 prometheus-client 替换）
try:
    from src.api.metrics import counter_inc, gauge_set
    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False
    def counter_inc(name, labels=None, value=1): pass
    def gauge_set(name, value, labels=None): pass


# ---------------------------------------------------------------------------
# 熔断器（Circuit Breaker）
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """熔断器：连续失败 N 次后断开，冷却期后半开试探一次。

    状态机：
        Closed (正常) ──失败 N 次──→ Open (断开)
            ↑                          │
            └─── 成功 ── Half-Open ←──┘ (冷却期到)
                                       │
                                       └──失败──→ Open
    """

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self._failures: Dict[str, int] = {}        # agent_id -> 连续失败次数
        self._opened_at: Dict[str, datetime] = {}  # agent_id -> 进入 Open 的时间

    def can_call(self, agent_id: str) -> bool:
        """是否允许调用此 Agent"""
        if agent_id not in self._opened_at:
            return True  # Closed
        # 检查冷却期是否已过
        elapsed = datetime.now(timezone.utc) - self._opened_at[agent_id]
        if elapsed > self.cooldown:
            # 进入 Half-Open，允许一次试探
            logger.info("Circuit half-open for agent %s (probing)", agent_id)
            return True
        return False  # Open，拒绝

    def record_failure(self, agent_id: str, error: Optional[str] = None):
        """记录一次失败"""
        self._failures[agent_id] = self._failures.get(agent_id, 0) + 1
        counter_inc(
            "agent_call_failures_total",
            {"agent_id": agent_id},
        )
        if self._failures[agent_id] >= self.failure_threshold:
            self._opened_at[agent_id] = datetime.now(timezone.utc)
            logger.warning(
                "Circuit OPEN for agent %s (failures=%d, error=%s)",
                agent_id, self._failures[agent_id], error,
            )

    def record_success(self, agent_id: str):
        """记录一次成功，重置计数"""
        self._failures.pop(agent_id, None)
        self._opened_at.pop(agent_id, None)

    def state(self, agent_id: str) -> str:
        """返回当前状态：closed / open / half_open"""
        if agent_id not in self._opened_at:
            return "closed"
        elapsed = datetime.now(timezone.utc) - self._opened_at[agent_id]
        if elapsed > self.cooldown:
            return "half_open"
        return "open"

    def reset(self, agent_id: str):
        """手动重置某个 Agent 的熔断器"""
        self._failures.pop(agent_id, None)
        self._opened_at.pop(agent_id, None)

    def stats(self) -> Dict[str, dict]:
        """返回所有 Agent 的熔断器状态"""
        result = {}
        for agent_id in set(list(self._failures.keys()) + list(self._opened_at.keys())):
            result[agent_id] = {
                "failures": self._failures.get(agent_id, 0),
                "state": self.state(agent_id),
            }
        return result


# ---------------------------------------------------------------------------
# 健康检查器
# ---------------------------------------------------------------------------


class HealthChecker:
    """Agent 健康检查器 — 后台任务定期扫描心跳超时 + 可选主动探活

    Args:
        registry: Agent 注册中心（src.protocols.agent_registry.registry）
        threshold_seconds: 心跳超时阈值（秒），超过则标记 offline
        scan_interval: 扫描间隔（秒）
        probe_enabled: 是否开启主动 HTTP 探活
        probe_interval: 主动探活间隔（秒）
    """

    def __init__(
        self,
        registry,
        threshold_seconds: int = 60,
        scan_interval: int = 15,
        probe_enabled: bool = True,
        probe_interval: int = 60,
    ):
        self.registry = registry
        self.threshold = timedelta(seconds=threshold_seconds)
        self.scan_interval = scan_interval
        self.probe_enabled = probe_enabled and _HTTPX_AVAILABLE
        self.probe_interval = probe_interval
        self.circuit_breaker = CircuitBreaker()
        self._task: Optional[asyncio.Task] = None
        self._probe_task: Optional[asyncio.Task] = None
        self._probe_timeout = 3.0  # 单次探活超时
        # 告警防重复：记录已发送 offline 告警的 agent_id
        # 同一 agent 在 offline 期间只发送一次告警，
        # 恢复 online 后从中移除，再次离线才能再次告警
        self._alerted_offline: Set[str] = set()

    async def start(self):
        """启动后台扫描任务"""
        if self._task is not None:
            logger.warning("HealthChecker already started")
            return
        self._task = asyncio.create_task(self._scan_loop())
        if self.probe_enabled:
            self._probe_task = asyncio.create_task(self._probe_loop())
        logger.info(
            "HealthChecker started (threshold=%ss, scan=%ss, probe=%s/%ss)",
            int(self.threshold.total_seconds()),
            self.scan_interval,
            "on" if self.probe_enabled else "off",
            self.probe_interval,
        )

    async def stop(self):
        """停止后台任务"""
        for task in (self._task, self._probe_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._probe_task = None
        logger.info("HealthChecker stopped")

    # ---- 心跳超时扫描 ----

    async def _scan_loop(self):
        """主扫描循环"""
        try:
            while True:
                await asyncio.sleep(self.scan_interval)
                try:
                    self._scan_once()
                except Exception as e:
                    logger.error("Health scan error: %s", e)
        except asyncio.CancelledError:
            logger.debug("Scan loop cancelled")
            raise

    def _scan_once(self):
        """扫描一次：标记心跳超时的 Agent 为 offline，恢复在线时发送通知

        状态变化处理：
        - online → offline：发送告警（仅一次，防重复）
        - offline → online：发送恢复通知，并从告警集合移除
        """
        now = datetime.now(timezone.utc)
        offline_events = []  # (agent_id, name, age_sec, reason) 待异步告警
        recover_events = []  # (agent_id, name) 待异步通知
        with self.registry._lock:
            for entry in self.registry._registry.values():
                age = now - entry.last_heartbeat
                # online → offline
                if age > self.threshold and entry.status == "online":
                    entry.status = "offline"
                    logger.warning(
                        "Agent %s marked offline (no heartbeat for %ss)",
                        entry.agent_id, int(age.total_seconds()),
                    )
                    counter_inc(
                        "agent_offline_events_total",
                        {"agent_id": entry.agent_id, "reason": "heartbeat_timeout"},
                    )
                    offline_events.append(
                        (entry.agent_id, entry.name, int(age.total_seconds()), "heartbeat_timeout")
                    )
                # offline → online（心跳自然恢复，例如 Agent 重启并主动上报心跳）
                elif age <= self.threshold and entry.status == "offline":
                    entry.status = "online"
                    logger.info(
                        "Agent %s recovered (heartbeat resumed after %ss)",
                        entry.agent_id, int(age.total_seconds()),
                    )
                    recover_events.append((entry.agent_id, entry.name))

        # 锁外异步发送告警，避免阻塞扫描循环
        for agent_id, name, age_sec, reason in offline_events:
            if agent_id not in self._alerted_offline:
                self._alerted_offline.add(agent_id)
                asyncio.create_task(
                    self._notify_feishu_offline(agent_id, name, age_sec, reason)
                )
        for agent_id, name in recover_events:
            if agent_id in self._alerted_offline:
                self._alerted_offline.discard(agent_id)
                asyncio.create_task(
                    self._notify_feishu_recover(agent_id, name, "heartbeat_resumed")
                )

    # ---- 主动探活 ----

    async def _probe_loop(self):
        """主动探活循环"""
        try:
            while True:
                await asyncio.sleep(self.probe_interval)
                try:
                    await self._probe_all()
                except Exception as e:
                    logger.error("Probe error: %s", e)
        except asyncio.CancelledError:
            logger.debug("Probe loop cancelled")
            raise

    async def _probe_all(self):
        """对所有 Agent 发起 HTTP /health 探测"""
        if not _HTTPX_AVAILABLE:
            return
        import httpx

        entries = list(self.registry._registry.values())
        if not entries:
            return

        async with httpx.AsyncClient(timeout=self._probe_timeout) as client:
            tasks = [self._probe_one(client, e) for e in entries]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _probe_one(self, client, entry):
        """探测单个 Agent"""
        url = (entry.url or "").rstrip("/")
        if not url:
            return
        health_url = f"{url}/health"
        agent_id = entry.agent_id
        # 记录探活前的状态，用于检测状态变化
        prev_status = entry.status
        try:
            r = await client.get(health_url)
            if r.status_code == 200:
                # 探活成功，更新心跳 + 在线
                self.registry.heartbeat(agent_id)
                counter_inc(
                    "agent_health_check_total",
                    {"agent_id": agent_id, "result": "success"},
                )
                # offline → online：发送恢复通知
                if prev_status == "offline" and agent_id in self._alerted_offline:
                    self._alerted_offline.discard(agent_id)
                    asyncio.create_task(
                        self._notify_feishu_recover(agent_id, entry.name, "probe_success")
                    )
            else:
                # 探活失败，标记 offline
                self.registry.mark_offline(agent_id)
                counter_inc(
                    "agent_health_check_total",
                    {"agent_id": agent_id, "result": f"http_{r.status_code}"},
                )
                logger.warning(
                    "Probe %s failed: HTTP %s", agent_id, r.status_code,
                )
                # online → offline：发送告警（防重复）
                if prev_status == "online" and agent_id not in self._alerted_offline:
                    self._alerted_offline.add(agent_id)
                    asyncio.create_task(
                        self._notify_feishu_offline(
                            agent_id, entry.name, 0, f"probe_http_{r.status_code}"
                        )
                    )
        except Exception as e:
            self.registry.mark_offline(agent_id)
            counter_inc(
                "agent_health_check_total",
                {"agent_id": agent_id, "result": "error"},
            )
            logger.warning("Probe %s error: %s", agent_id, str(e)[:100])
            # online → offline：发送告警（防重复）
            if prev_status == "online" and agent_id not in self._alerted_offline:
                self._alerted_offline.add(agent_id)
                asyncio.create_task(
                    self._notify_feishu_offline(
                        agent_id, entry.name, 0, f"probe_error: {str(e)[:80]}"
                    )
                )

    # ---- 飞书告警 ----

    async def _notify_feishu_offline(
        self, agent_id: str, name: str, age_sec: int, reason: str
    ):
        """Agent 离线告警：发送飞书卡片消息"""
        try:
            from src.config import settings
            if not self._is_alert_enabled():
                logger.debug(
                    "Feishu alert skipped (disabled): agent=%s offline (%s)",
                    agent_id, reason,
                )
                return

            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            title = f"{settings.alert_feishu_title_prefix} Agent 离线告警"
            content = (
                f"**Agent 名称**：{name}\n"
                f"**Agent ID**：`{agent_id}`\n"
                f"**触发时间**：{now}\n"
                f"**离线原因**：{reason}\n"
                f"**心跳超时**：{age_sec}s\n\n"
                f"⚠️ 请尽快检查 Agent 服务状态"
            )
            await self._send_feishu_card(title, content, template="red")
            logger.info("Feishu offline alert sent: agent=%s reason=%s", agent_id, reason)
        except Exception as e:
            # 告警失败不影响主流程，仅记录日志
            logger.error("Feishu offline alert failed (agent=%s): %s", agent_id, e)

    async def _notify_feishu_recover(
        self, agent_id: str, name: str, reason: str
    ):
        """Agent 恢复在线通知：发送飞书卡片消息"""
        try:
            from src.config import settings
            if not self._is_alert_enabled():
                logger.debug(
                    "Feishu alert skipped (disabled): agent=%s recovered (%s)",
                    agent_id, reason,
                )
                return

            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            title = f"{settings.alert_feishu_title_prefix} Agent 恢复在线"
            content = (
                f"**Agent 名称**：{name}\n"
                f"**Agent ID**：`{agent_id}`\n"
                f"**恢复时间**：{now}\n"
                f"**恢复原因**：{reason}\n\n"
                f"✅ Agent 已恢复正常服务"
            )
            await self._send_feishu_card(title, content, template="green")
            logger.info("Feishu recover alert sent: agent=%s reason=%s", agent_id, reason)
        except Exception as e:
            logger.error("Feishu recover alert failed (agent=%s): %s", agent_id, e)

    def _is_alert_enabled(self) -> bool:
        """判断飞书告警是否启用"""
        try:
            from src.config import settings
            # 飞书告警需要同时满足：
            # 1. alert_feishu_enabled 开关打开
            # 2. mcp_feishu_enabled 已配置（复用其凭证）
            # 3. 接收者 ID 已配置
            return (
                settings.alert_feishu_enabled
                and settings.mcp_feishu_enabled
                and bool(settings.alert_feishu_receive_id)
                and bool(settings.mcp_feishu_app_id)
                and bool(settings.mcp_feishu_app_secret)
            )
        except Exception:
            return False

    async def _send_feishu_card(
        self, title: str, content: str, template: str = "turquoise"
    ):
        """发送飞书卡片消息（独立异步方法，不依赖 langchain tool）

        Args:
            title: 卡片标题
            content: 卡片正文（支持 lark_md 语法）
            template: 卡片颜色模板（red/green/turquoise/blue/orange 等）
        """
        # 延迟导入避免循环依赖；飞书工具模块可能未启用
        from src.config import settings

        # 复用 mcp_tools.feishu 的底层 API 函数（绕过 langchain tool 装饰）
        from src.mcp_tools.feishu import _feishu_request

        card = {
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
            ],
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
        }
        body = {
            "receive_id": settings.alert_feishu_receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        }
        result = _feishu_request(
            "POST",
            "/im/v1/messages",
            params={"receive_id_type": settings.alert_feishu_receive_id_type},
            body=body,
        )
        if result.get("code") != 0:
            logger.warning(
                "Feishu message send failed: code=%s msg=%s",
                result.get("code"), result.get("msg"),
            )

    # ---- 状态查询 ----

    def get_status(self) -> dict:
        """返回所有 Agent 的健康状态总览"""
        with self.registry._lock:
            agents = []
            now = datetime.now(timezone.utc)
            for entry in self.registry._registry.values():
                age_sec = int((now - entry.last_heartbeat).total_seconds())
                agents.append({
                    "agent_id": entry.agent_id,
                    "name": entry.name,
                    "url": entry.url,
                    "status": entry.status,
                    "last_heartbeat_age_sec": age_sec,
                    "circuit_state": self.circuit_breaker.state(entry.agent_id),
                    "failures": self.circuit_breaker._failures.get(entry.agent_id, 0),
                })

        total = len(agents)
        online = sum(1 for a in agents if a["status"] == "online")
        offline = total - online

        # 同步到 Prometheus gauge
        gauge_set("agent_registry_total", total, {"status": "all"})
        gauge_set("agent_registry_total", online, {"status": "online"})
        gauge_set("agent_registry_total", offline, {"status": "offline"})

        return {
            "threshold_seconds": int(self.threshold.total_seconds()),
            "scan_interval_seconds": self.scan_interval,
            "probe_enabled": self.probe_enabled,
            "probe_interval_seconds": self.probe_interval,
            "total_agents": total,
            "online_agents": online,
            "offline_agents": offline,
            "agents": agents,
            "circuit_breakers": self.circuit_breaker.stats(),
        }


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

_health_checker: Optional[HealthChecker] = None


def get_health_checker(registry=None) -> HealthChecker:
    """获取全局 HealthChecker 单例

    首次调用时会自动注入默认 registry（若未显式传入）。
    """
    global _health_checker
    if _health_checker is None:
        if registry is None:
            from src.protocols.agent_registry import registry as default_registry
            registry = default_registry
        _health_checker = HealthChecker(registry=registry)
    return _health_checker


def reset_health_checker():
    """重置单例（测试用）"""
    global _health_checker
    _health_checker = None
