from typing import Callable, List, Optional
import logging
import re
import time
from langchain_core.tools import tool
from src.rag.retriever import HybridRetriever

logger = logging.getLogger(__name__)


# 简单的内存 FAQ 存储（用于 search_faq 工具）
# 支持中英文关键词匹配，覆盖高频客服场景
_FAQ_STORE = {
    # 英文关键词
    "reset password": "To reset your password: Go to Login > Forgot Password. Enter your email. Check your inbox for a reset link valid for 30 minutes.",
    "change plan": "To change your plan: Go to Settings > Billing > Change Plan. Upgrade takes effect immediately. Downgrade takes effect at the end of the billing cycle.",
    "更改计划": "设置 > 账单 > 更改计划。升级立即生效，降级在计费周期结束时生效。",
    "修改计划": "设置 > 账单 > 更改计划。升级立即生效，降级在计费周期结束时生效。",
    "订阅计划": "设置 > 账单 > 更改计划。升级立即生效，降级在计费周期结束时生效。",
    "cancel subscription": "To cancel: Go to Settings > Billing > Cancel Subscription. You retain access until the end of the billing period.",
    "api key": "To get an API Key: Go to Console > Developer Settings > API Keys > Generate New Key. Copy immediately — it won't be shown again.",
    "403 error": "403 errors mean access denied. Common causes: 1) Invalid/expired API Key, 2) Domain not whitelisted, 3) CORS configuration missing.",
    "sso": "CloudSync supports SSO via Okta, Azure AD, Google Workspace, and custom SAML 2.0. Go to Settings > SSO to configure.",
    "encryption": "CloudSync encrypts data in transit (TLS 1.3) and at rest (AES-256). Enterprise plans include customer-managed encryption keys.",
    "two factor": "Enable 2FA at Settings > Security > Two-Factor Authentication. Choose authenticator app or SMS.",
    "sync not working": "Check: 1) Providers are authenticated, 2) Available storage, 3) The files are not locked by another process.",
    "pricing": "Plans: Free (5GB, 2 providers), Pro ($15/mo, 100GB, 5 providers), Enterprise ($50/user/mo, unlimited).",
    # 中文关键词（映射到相同答案）
    "重置密码": "登录页面 > 忘记密码 > 输入邮箱 > 查收重置链接（30 分钟内有效）。",
    "修改计划": "设置 > 账单 > 更改计划。升级立即生效，降级在计费周期结束时生效。",
    "取消订阅": "设置 > 账单 > 取消订阅。在计费周期结束前仍可继续使用。",
    "获取 API Key": "控制台 > 开发者设置 > API 密钥 > 生成新密钥。请立即复制，生成后将不再显示。",
    "403 错误": "403 表示访问被拒绝。常见原因：1) API Key 无效/过期 2) 域名未加入白名单 3) CORS 配置缺失。",
    "SSO 配置": "CloudSync 支持 Okta、Azure AD、Google Workspace 和自定义 SAML 2.0。前往设置 > SSO 进行配置。",
    "加密方式": "CloudSync 传输中加密（TLS 1.3），静态数据加密（AES-256）。企业版支持客户自管加密密钥。",
    "两步验证": "设置 > 安全 > 两步验证。可选择验证器应用或短信验证。",
    "同步失败": "检查：1) 服务商是否已认证 2) 剩余存储空间 3) 文件是否被其他进程锁定。",
    "定价方案": "免费版：5GB 存储，2 个提供商；专业版：$15/月，100GB 存储；企业版：定制报价，无限存储。",
    "退款": "免费计划用户无法直接申请退款，已为您转接人工客服处理。",
    "取消订单": "设置 > 订单管理 > 取消订单。取消后数据将保留 30 天。",
}


def _faq_search(query: str) -> Optional[str]:
    """简单的 FAQ 关键词匹配"""
    query_lower = query.lower()
    for keyword, answer in _FAQ_STORE.items():
        if keyword in query_lower:
            return answer
    return None


# ---------------------------------------------------------------------------
# 权限缓存
# ---------------------------------------------------------------------------

class PermissionCache:
    """权限快照缓存 — 既快又不脏

    设计原则：
        1. 缓存只放权限快照 + 版本号，不放完整权限树
        2. 权限变更后推送失效事件
        3. 执行敏感操作前再查一次权威数据源

    缓存结构：
        key: user_id:tenant_id
        value: {
            "snapshot": {"roles": [...], "plan": "...", "access_levels": [...]},
            "version": 42,          # 版本号，变更时递增
            "ttl": 300,             # 缓存时间 5 分钟
            "expired": false        # 是否已失效
        }

    失效策略：
        - 被动失效：TTL 到期自动过期
        - 主动失效：权限变更时推送 invalidate()
        - 半主动失效：敏感操作前强制 refresh()
    """

    def __init__(self, default_ttl: int = 300):
        self._cache: dict = {}
        self._default_ttl = default_ttl

    def get(self, user_id: str, tenant_id: str) -> Optional[dict]:
        """获取缓存的权限快照"""
        key = f"{user_id}:{tenant_id}"
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.get("expired", False):
            del self._cache[key]
            return None
        if time.time() - entry.get("cached_at", 0) > entry["ttl"]:
            entry["expired"] = True
            return None
        return entry

    def put(self, user_id: str, tenant_id: str, snapshot: dict, version: int = 0):
        """写入缓存"""
        key = f"{user_id}:{tenant_id}"
        self._cache[key] = {
            "snapshot": snapshot,
            "version": version,
            "ttl": self._default_ttl,
            "cached_at": time.time(),
            "expired": False,
        }

    def invalidate(self, user_id: str, tenant_id: str = ""):
        """主动失效 — 权限变更后调用"""
        if tenant_id:
            key = f"{user_id}:{tenant_id}"
            if key in self._cache:
                self._cache[key]["expired"] = True
                logger.info("Permission cache invalidated: %s", key)
        else:
            # 失效该用户所有租户
            for key in list(self._cache.keys()):
                if key.startswith(f"{user_id}:"):
                    self._cache[key]["expired"] = True
            logger.info("Permission cache invalidated for user: %s", user_id)

    def refresh(self, user_id: str, tenant_id: str) -> Optional[dict]:
        """强制刷新 — 敏感操作前调用"""
        key = f"{user_id}:{tenant_id}"
        if key in self._cache:
            self._cache[key]["expired"] = True
        return None  # 调用方需要从权威数据源重新获取

    def clear(self):
        """清空缓存"""
        self._cache.clear()

    def get_snapshot(self, user_id: str, tenant_id: str) -> Optional[dict]:
        """获取缓存中的权限快照（不含版本信息）"""
        entry = self.get(user_id, tenant_id)
        if entry:
            return entry.get("snapshot")
        return None

    def get_entry(self, user_id: str, tenant_id: str) -> Optional[dict]:
        """获取缓存条目（含版本和过期状态）"""
        key = f"{user_id}:{tenant_id}"
        return self._cache.get(key)


# 全局权限缓存单例（跨请求共享）
_global_permission_cache: Optional[PermissionCache] = None


def get_permission_cache() -> PermissionCache:
    """获取全局权限缓存实例"""
    global _global_permission_cache
    if _global_permission_cache is None:
        _global_permission_cache = PermissionCache()
    return _global_permission_cache


def invalidate_user_permissions(user_id: str, tenant_id: str = ""):
    """权限变更回调 — 当用户角色/计划/权限变更时调用"""
    cache = get_permission_cache()
    cache.invalidate(user_id, tenant_id)
    logger.info("Permission invalidation pushed: user=%s, tenant=%s", user_id, tenant_id)


# ---------------------------------------------------------------------------
# 统一鉴权中间件
# ---------------------------------------------------------------------------

class PermissionChecker:
    """统一鉴权中间件 — 所有工具执行前必须通过此检查

    核心原则：鉴权是代码逻辑，不是 LLM 的逻辑。
    工具描述中只写"什么时候用"，不写"谁能用"。
    权限判断在 create_tools 闭包中完成，LLM 看到的只是工具名称和描述。

    三层防护：
        1. 工具级权限：用户角色是否允许调用此工具
        2. 参数级校验：LLM 传入的参数是否超出用户权限范围
        3. 审计日志：所有越权尝试记录日志

    权限缓存：
        - 缓存只放快照 + 版本号，TTL 5 分钟
        - 权限变更时推送失效事件
        - 敏感操作前强制刷新权威数据源
    """

    # 敏感操作列表 — 执行前必须查权威数据源
    SENSITIVE_OPERATIONS = {
        "manage_billing",
        "manage_users",
        "manage_sso",
        "escalate_to_human",
    }

    def __init__(
        self,
        user_id: str,
        tenant_id: str,
        roles: Optional[List[str]] = None,
        access_levels: Optional[List[str]] = None,
        plan: str = "free",
        permission_cache: Optional[PermissionCache] = None,
        authority_source: Optional[Callable] = None,
    ):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.roles = roles or []
        self.access_levels = access_levels or ["public"]
        self.plan = plan
        self._audit_log: List[str] = []
        self._cache = permission_cache or PermissionCache()
        self._authority_source = authority_source  # 权威数据源回调

        # 写入缓存
        self._cache.put(
            user_id, tenant_id,
            snapshot={
                "roles": self.roles,
                "plan": self.plan,
                "access_levels": self.access_levels,
            },
            version=0,
        )

    def check(self, tool_name: str, resource_scope: Optional[str] = None) -> bool:
        """检查用户是否有权限调用此工具

        缓存策略：
            1. 只读工具 → 用缓存快照（快）
            2. 敏感工具 → 先查缓存，缓存命中且未过期 → 用缓存
                            缓存未命中或过期 → 调权威数据源
        """
        # 规则 1: 只读工具（搜索/FAQ/查询订单）对所有用户开放
        if tool_name in ("search_knowledge_base", "search_faq", "query_order"):
            return True

        # 规则 2: 转人工需要确认身份
        if tool_name == "escalate_to_human":
            # 敏感操作 → 强制查权威数据源
            if self._authority_source:
                fresh = self._refresh_authority()
                if fresh:
                    self.roles = fresh.get("roles", [])
                    self.plan = fresh.get("plan", "free")
                    self.access_levels = fresh.get("access_levels", ["public"])

            if not self.user_id or self.user_id == "anonymous":
                self._audit("ESCALATE_DENIED", tool_name, "anonymous user")
                return False
            return True

        # 规则 3: 受限工具（未来扩展）
        restricted_tools = {
            "manage_billing": ["admin", "billing_manager"],
            "manage_users": ["admin"],
            "manage_sso": ["admin"],
        }
        if tool_name in restricted_tools:
            # 敏感操作 → 强制查权威数据源
            if self._authority_source:
                fresh = self._refresh_authority()
                if fresh:
                    self.roles = fresh.get("roles", [])
                    self.plan = fresh.get("plan", "free")
                    self.access_levels = fresh.get("access_levels", ["public"])

            required_roles = restricted_tools[tool_name]
            if not any(r in self.roles for r in required_roles):
                self._audit("TOOL_DENIED", tool_name, f"missing roles: {required_roles}")
                return False

        # 规则 4: 资源级权限
        if resource_scope:
            return self._check_resource_permission(resource_scope)

        return True

    def _refresh_authority(self) -> Optional[dict]:
        """从权威数据源刷新权限信息

        调用权限变更回调，返回最新的权限快照。
        如果权威数据源不可用，返回 None 继续使用缓存。
        """
        if not self._authority_source:
            return None
        try:
            fresh = self._authority_source(self.user_id, self.tenant_id)
            if fresh:
                # 更新缓存
                self._cache.put(
                    self.user_id, self.tenant_id,
                    snapshot=fresh,
                    version=fresh.get("version", 0),
                )
                logger.info(
                    "Authority refreshed for %s:%s, version=%s",
                    self.user_id, self.tenant_id,
                    fresh.get("version", 0),
                )
            return fresh
        except Exception as e:
            logger.warning("Authority refresh failed: %s", e)
            return None


    def validate_params(
        self, tool_name: str, params: dict
    ) -> tuple[bool, str]:
        """参数级校验：LLM 传入的参数是否超出用户权限范围

        核心逻辑：
            1. 参数中的资源范围（如 plan、tenant_id）用后端重算
            2. 如果超出用户权限 → 拒绝
            3. 记录审计日志

        Returns:
            (allowed, reason)
            - allowed: True 表示参数合法
            - reason: 拒绝原因（允许时为 ""）
        """
        # 规则 1: 计划升级 — free 用户不能直接升级为 enterprise
        if tool_name == "manage_billing":
            requested_plan = params.get("plan", "").lower()
            allowed_plans = self._get_allowed_upgrade_paths()
            if requested_plan and requested_plan not in allowed_plans:
                reason = (
                    f"参数越权：当前计划 {self.plan}，"
                    f"不允许直接升级到 {requested_plan}。"
                    f"允许升级的目标计划: {', '.join(allowed_plans)}"
                )
                self._audit("PARAM_VIOLATION", tool_name, reason)
                return False, reason

        # 规则 2: 租户隔离 — 不能操作其他租户的资源
        requested_tenant = params.get("tenant_id", "")
        if requested_tenant and requested_tenant != self.tenant_id:
            reason = (
                f"参数越权：当前租户 {self.tenant_id}，"
                f"不允许操作租户 {requested_tenant} 的资源"
            )
            self._audit("TENANT_VIOLATION", tool_name, reason)
            return False, reason

        # 规则 3: 用户 ID — 不能操作其他用户的资源
        requested_user = params.get("user_id", "")
        if requested_user and requested_user != self.user_id:
            # 管理员可以操作其他用户
            if "admin" not in self.roles:
                reason = (
                    f"参数越权：当前用户 {self.user_id}，"
                    f"不允许操作用户 {requested_user} 的资源"
                )
                self._audit("USER_VIOLATION", tool_name, reason)
                return False, reason

        return True, ""

    def _get_allowed_upgrade_paths(self) -> List[str]:
        """获取当前计划允许升级到的目标计划"""
        upgrade_paths = {
            "free": ["pro"],
            "pro": ["enterprise"],
            "enterprise": [],  # 最高级，无法升级
        }
        return upgrade_paths.get(self.plan, [])

    def _audit(self, event_type: str, tool_name: str, reason: str):
        """记录审计日志"""
        entry = (
            f"[AUDIT] {event_type} | tool={tool_name} | "
            f"user={self.user_id} | tenant={self.tenant_id} | "
            f"plan={self.plan} | reason={reason}"
        )
        self._audit_log.append(entry)
        logger.warning(entry)

    def _check_resource_permission(self, resource: str) -> bool:
        """检查资源级权限"""
        resource_permissions = {
            "billing": ["admin", "billing_manager"],
            "admin_console": ["admin"],
            "api_keys": ["admin", "developer"],
            "user_profile": ["admin", "user"],  # 用户可以查看自己的 profile
        }
        required_roles = resource_permissions.get(resource, [])
        if not required_roles:
            return True  # 未定义的公共资源，默认开放
        return any(r in self.roles for r in required_roles)


# ---------------------------------------------------------------------------
# 权限版本感知 & 多工具任务检查点
# ---------------------------------------------------------------------------

class PermissionVersionTracker:
    """权限版本感知检查点 — 多工具任务中途权限变更检测

    核心逻辑：
        1. 任务开始时记录权限版本号
        2. 每个关键步骤执行前检查版本是否变化
        3. 版本变化 → 暂停任务 + 重新规划
        4. 已执行动作记录补偿状态（undo/redo）

    使用方式：
        tracker = PermissionVersionTracker()
        tracker.begin_session(user_id, tenant_id, initial_version=0)

        # 步骤 1
        tracker.checkpoint("step_1", tool_name="search_knowledge_base")
        result1 = tool1(...)

        # 步骤 2 — 如果权限在步骤 1 和 2 之间变了，这里会抛出 PermissionVersionChanged
        tracker.checkpoint("step_2", tool_name="manage_billing")
        result2 = tool2(...)
    """

    def __init__(self, cache: Optional[PermissionCache] = None):
        self._cache = cache or get_permission_cache()
        self._session_version: Optional[int] = None
        self._session_key: Optional[str] = None
        self._actions: List[dict] = []  # 已执行动作记录
        self._compensation_log: List[dict] = []  # 补偿记录

    def begin_session(self, user_id: str, tenant_id: str, initial_version: int = 0):
        """开始一个新任务会话，记录初始权限版本"""
        self._session_key = f"{user_id}:{tenant_id}"
        self._session_version = initial_version
        self._actions.clear()
        self._compensation_log.clear()

        # 初始化缓存条目（如果还没有）
        uid, tid = user_id, tenant_id
        if not self._cache.get_entry(uid, tid):
            self._cache.put(uid, tid, {
                "roles": [],
                "plan": "free",
                "access_levels": ["public"],
            }, version=initial_version)

        logger.info(
            "Permission session started: user=%s, tenant=%s, version=%s",
            user_id, tenant_id, initial_version,
        )

    def checkpoint(
        self,
        step_name: str,
        tool_name: str,
        authority_source: Optional[Callable] = None,
    ) -> dict:
        """在每个关键步骤前检查权限版本

        Args:
            step_name: 当前步骤名称
            tool_name: 即将执行的工具名
            authority_source: 权威数据源回调（用于版本变化时刷新）

        Returns:
            {"status": "ok" | "interrupted", "version": int, "reason": str}

        Raises:
            PermissionVersionChanged: 版本变化时抛出，调用方应暂停任务
        """
        if self._session_key is None:
            raise RuntimeError("Session not started. Call begin_session() first.")

        # 获取当前权限版本
        uid, tid = self._session_key.split(":", 1)
        current_entry = self._cache.get(uid, tid)
        if current_entry is None:
            # 缓存未命中 → 强制刷新权威数据源
            if authority_source:
                fresh = authority_source(uid, tid)
                if fresh:
                    version = fresh.get("version", 0)
                    snapshot = {
                        "roles": fresh.get("roles", []),
                        "plan": fresh.get("plan", "free"),
                        "access_levels": fresh.get("access_levels", ["public"]),
                    }
                    self._cache.put(uid, tid, snapshot, version)
                    current_entry = self._cache.get_entry(uid, tid)

        if current_entry is None:
            # 缓存完全不可用 → 视为版本变化（权限可能已被撤销）
            reason = (
                f"权限缓存不可用，步骤 '{step_name}' 已暂停。"
                f"请重新验证用户权限。"
            )
            logger.warning("Permission cache unavailable: %s", reason)
            compensation = {
                "strategy": "manual_review",
                "actions_to_undo": [
                    {"step": a["step"], "tool": a["tool"]}
                    for a in self._actions
                ],
                "reason": "权限缓存不可用，需人工审核",
            }
            self._compensation_log.append(compensation)
            raise PermissionVersionChanged(
                step_name=step_name,
                tool_name=tool_name,
                old_version=self._session_version or 0,
                new_version=-1,  # -1 表示不可用
                actions_executed=self._actions.copy(),
                compensation=compensation,
            )

        current_version = current_entry.get("version", 0)

        # 检查版本是否变化
        if self._session_version is not None and current_version > self._session_version:
            # 版本变化 → 中断任务
            reason = (
                f"权限版本从 {self._session_version} 变更为 {current_version}，"
                f"步骤 '{step_name}' 已暂停。"
            )
            logger.warning("Permission version changed: %s", reason)

            # 记录已执行动作的补偿状态
            compensation = self._compute_compensation(step_name, tool_name, current_version)
            self._compensation_log.append(compensation)

            raise PermissionVersionChanged(
                step_name=step_name,
                tool_name=tool_name,
                old_version=self._session_version,
                new_version=current_version,
                actions_executed=self._actions.copy(),
                compensation=compensation,
            )

        # 记录当前步骤
        self._actions.append({
            "step": step_name,
            "tool": tool_name,
            "version_at_check": current_version,
            "timestamp": time.time(),
        })

        # 更新会话版本（取最大值，防止回退）
        if self._session_version is None or current_version > self._session_version:
            self._session_version = current_version

        return {"status": "ok", "version": current_version, "reason": ""}

    def _compute_compensation(
        self,
        interrupted_step: str,
        tool_name: str,
        new_version: int,
    ) -> dict:
        """计算已执行动作的补偿策略

        返回：
            {
                "strategy": "rollback" | "retry" | "manual_review",
                "actions_to_undo": [...],
                "reason": str,
            }
        """
        # 策略 1: 如果中断前只执行了只读操作 → 重试即可
        readonly_actions = [
            a for a in self._actions
            if a["tool"] in ("search_knowledge_base", "search_faq")
        ]

        if readonly_actions and not self._actions[len(readonly_actions):]:
            # 只执行了只读操作 → 可以安全重试
            return {
                "strategy": "retry",
                "actions_to_undo": [],
                "reason": "仅执行了只读操作，可安全重试",
            }

        # 策略 2: 如果执行了写操作 → 需要回滚
        write_actions = [
            a for a in self._actions
            if a["tool"] not in ("search_knowledge_base", "search_faq")
        ]

        if write_actions:
            return {
                "strategy": "rollback",
                "actions_to_undo": [
                    {"step": a["step"], "tool": a["tool"]}
                    for a in write_actions
                ],
                "reason": f"执行了 {len(write_actions)} 个写操作，需要回滚",
            }

        # 策略 3: 无法自动处理 → 人工审核
        return {
            "strategy": "manual_review",
            "actions_to_undo": [],
            "reason": "无法自动确定补偿策略，需人工审核",
        }

    def get_session_status(self) -> dict:
        """获取当前会话状态"""
        return {
            "session_key": self._session_key,
            "version": self._session_version,
            "actions_count": len(self._actions),
            "compensation_log": self._compensation_log,
        }


class PermissionVersionChanged(Exception):
    """权限版本变更异常 — 多工具任务中途权限变化时抛出"""

    def __init__(
        self,
        step_name: str,
        tool_name: str,
        old_version: int,
        new_version: int,
        actions_executed: List[dict],
        compensation: dict,
    ):
        self.step_name = step_name
        self.tool_name = tool_name
        self.old_version = old_version
        self.new_version = new_version
        self.actions_executed = actions_executed
        self.compensation = compensation
        super().__init__(
            f"Permission version changed from {old_version} to {new_version} "
            f"during step '{step_name}'. Compensation: {compensation}"
        )


# ---------------------------------------------------------------------------
# 工具创建
# ---------------------------------------------------------------------------

def create_tools(
    retriever: HybridRetriever = None,
    user_id: str = "",
    tenant_id: str = "",
    user_access_levels: Optional[List[str]] = None,
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
):
    """创建客服 Agent 的工具列表

    权限模型：
        身份: user_id + tenant_id + roles + plan
        工具权限: 只读工具（公开）/ 转人工（需身份）/ 受限工具（需角色）
        资源权限: 按资源范围隔离（billing/admin_console/api_keys）

    权限缓存：
        - 缓存只放快照 + 版本号，TTL 5 分钟
        - 权限变更时推送 invalidate()
        - 敏感操作前强制 refresh() 权威数据源

    所有权限检查在工具执行前完成，LLM 无法绕过。
    """
    checker = PermissionChecker(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles or [],
        access_levels=user_access_levels or ["public"],
        plan=plan,
        permission_cache=PermissionCache(),
        authority_source=authority_source,
    )

    @tool
    def search_knowledge_base(query: str) -> str:
        """搜索产品知识库获取技术文档和配置指南。

        当用户询问关于 API、SSO、配置、错误排查等需要产品文档的问题时使用。
        输入应是一个简洁的搜索查询，如 "SSO Okta 配置" 或 "403 错误排查"。

        Args:
            query: 搜索关键词（使用技术术语，不是完整句子）
        """
        # 权限检查（代码逻辑，LLM 无法绕过）
        if not checker.check("search_knowledge_base"):
            return "[权限不足] 您没有权限调用此工具。如需帮助请联系管理员。"

        if retriever is None:
            return "知识库当前不可用。请转人工客服。"

        try:
            results = retriever.search(
                query,
                top_k=3,
                user_id=user_id,
                tenant_id=tenant_id,
                user_access_levels=checker.access_levels,
            )
            if not results:
                return "未找到相关文档。建议转人工客服获取帮助。"

            # 检查是否有权限过滤
            access_filtered = sum(
                doc.metadata.get("access_filtered", 0) for doc, _ in results
            )

            parts = []
            for i, (doc, _) in enumerate(results, 1):
                source = doc.metadata.get("source", "unknown")
                content = doc.page_content[:500]
                parts.append(f"[Doc {i} - {source}]\n{content}")

            result_text = "\n\n---\n\n".join(parts)

            if access_filtered > 0:
                result_text += (
                    f"\n\n[注：本次检索有 {access_filtered} 条结果因权限不足被过滤]"
                )

            return result_text
        except Exception as e:
            return f"知识库搜索出错: {str(e)}。请尝试其他关键词或转人工。"

    @tool
    def search_faq(query: str) -> str:
        """FAQ 搜索常见问题库获取精确匹配的答案。

        当用户询问简单事实性问题（如密码重置、套餐变更、取消订阅等）时优先使用。

        Args:
            query: 问题的关键词，如 "reset password" 或 "change plan"
        """
        # 权限检查
        if not checker.check("search_faq"):
            return "[权限不足] 您没有权限调用此工具。如需帮助请联系管理员。"

        result = _faq_search(query)
        if result:
            return f"[FAQ Match] {result}"
        return "FAQ 中未找到匹配项。请尝试 search_knowledge_base 在完整知识库中搜索。"

    @tool
    def escalate_to_human(reason: str) -> str:
        """将当前对话转接人工客服。

        当以下情况时调用此工具：
        1. 用户明确要求转人工
        2. 问题超出知识库覆盖范围
        3. 需要账号操作（退款、删除数据等）
        4. 已进行 2 轮搜索仍未解决

        Args:
            reason: 转接原因，供人工客服参考
        """
        # 权限检查：需要确认身份
        if not checker.check("escalate_to_human"):
            return "[权限不足] 您没有权限调用此工具。如需帮助请联系管理员。"

        # 参数校验：reason 不能包含危险指令
        dangerous_patterns = [
            "ignore all", "forget all", "system prompt",
            "忽略所有", "忘记所有", "系统提示",
        ]
        reason_lower = reason.lower()
        if any(p in reason_lower for p in dangerous_patterns):
            checker._audit("PROMPT_INJECTION", "escalate_to_human", reason)
            return "[安全拦截] 检测到可疑输入，已拒绝处理。"

        return f"[Escalated to Human] 已为您转接人工客服。转接原因：{reason}。请稍候，客服专员将很快为您服务。"

    # ====================================================================
    # 执行工具（v1.0 新增）— 让 Agent 真正解决问题
    # ====================================================================

    @tool
    def query_order(order_id: str) -> str:
        """查询订单状态和物流信息。

        当用户询问订单状态、物流进度、发货时间等问题时使用。
        需要用户提供订单号（格式如 ORD-123456）。

        Args:
            order_id: 订单号，如 "ORD-123456"
        """
        if not checker.check("query_order"):
            return "[权限不足] 您没有权限查询订单。"

        if not order_id or len(order_id) < 5:
            return "请提供有效的订单号（如 ORD-123456）。"

        # 调用订单适配器
        try:
            from src.adapters.base import AdapterFactory
            order_adapter = AdapterFactory.get_order_adapter()
            result = order_adapter.query_order(order_id, user_id)
            if result and "error" in result:
                return f"未找到订单 {order_id}。请检查订单号是否正确。"
            if result:
                status = result.get("status", "unknown")
                tracking = result.get("tracking_number", "N/A")
                carrier = result.get("carrier", "N/A")
                est = result.get("estimated_delivery", "N/A")
                return (
                    f"订单 {order_id} 状态：{status}\n"
                    f"物流公司：{carrier} ({tracking})\n"
                    f"预计送达：{est}"
                )
        except Exception as e:
            logger.warning("Order query adapter failed: %s", e)

        return "订单查询服务暂时不可用，请稍后重试或转人工客服。"

    @tool
    def apply_refund(order_id: str, reason: str) -> str:
        """申请退款。

        当用户要求退款时使用。
        注意：此操作涉及资产变更，需要用户确认后才能执行。

        Args:
            order_id: 订单号
            reason: 退款原因
        """
        # 权限检查：退款需要 pro 或以上计划
        if checker.plan == "free":
            checker._audit("PLAN_RESTRICTED", "apply_refund",
                          f"free plan cannot refund, order={order_id}")
            return (
                "抱歉，免费计划用户无法直接申请退款。"
                "已为您转接人工客服处理。"
            )

        if not checker.check("apply_refund"):
            return "[权限不足] 您没有权限申请退款。"

        # 参数校验
        if not order_id or not reason:
            return "请提供订单号和退款原因。"

        # 高风险操作：记录审计日志
        checker._audit("REFUND_REQUEST", "apply_refund",
                       f"order={order_id}, reason={reason}")

        # 调用工单适配器创建退款工单
        try:
            from src.adapters.base import AdapterFactory
            ticket_adapter = AdapterFactory.get_ticket_adapter()
            ticket = ticket_adapter.create_ticket(
                user_id=user_id,
                subject=f"退款申请 - {order_id}",
                description=f"原因: {reason}",
                priority="high",
            )
            return (
                f"[退款申请已提交]\n"
                f"订单号: {order_id}\n"
                f"退款原因: {reason}\n"
                f"工单号: {ticket.get('ticket_id', 'N/A')}\n"
                f"状态: 待人工审核\n\n"
                f"人工客服将在 24 小时内处理您的退款申请。"
            )
        except Exception as e:
            logger.warning("Ticket adapter failed: %s", e)
            return (
                "退款申请已记录，工单系统暂时不可用。"
                "人工客服将在 24 小时内处理您的退款申请。"
            )

    @tool
    def cancel_order(order_id: str) -> str:
        """取消订单。

        当用户要求取消订单时使用。
        注意：此操作涉及资产变更，需要用户确认后才能执行。

        Args:
            order_id: 订单号
        """
        # 权限检查：取消订单需要 pro 或以上计划
        if checker.plan == "free":
            checker._audit("PLAN_RESTRICTED", "cancel_order",
                          f"free plan cannot cancel, order={order_id}")
            return (
                "抱歉，免费计划用户无法直接取消订单。"
                "已为您转接人工客服处理。"
            )

        if not checker.check("cancel_order"):
            return "[权限不足] 您没有权限取消订单。"

        if not order_id:
            return "请提供订单号。"

        # 高风险操作：记录审计日志
        checker._audit("CANCEL_REQUEST", "cancel_order", f"order={order_id}")

        # 调用订单适配器取消
        try:
            from src.adapters.base import AdapterFactory
            order_adapter = AdapterFactory.get_order_adapter()
            result = order_adapter.cancel_order(order_id, user_id)
            if result.get("success"):
                return f"订单 {order_id} 已成功取消。"
            return f"取消订单失败：{result.get('error', '未知原因')}"
        except Exception as e:
            logger.warning("Cancel order adapter failed: %s", e)
            return (
                "取消订单请求已记录，系统暂时不可用。"
                "人工客服将核实后为您取消订单。"
            )

    return [search_knowledge_base, search_faq, escalate_to_human,
            query_order, apply_refund, cancel_order]
