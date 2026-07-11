"""Enterprise Agent 工具系统

权限模型：
    身份: user_id + tenant_id + roles + plan
    工具权限: 只读工具（公开）/ 转人工（需身份）/ 受限工具（需角色）
    资源权限: 按资源范围隔离（billing/admin_console/api_keys）
    权限缓存: TTL 5 分钟 + 变更推送失效 + 敏感操作前强制刷新
    版本感知: 多工具任务中途权限变化 → 暂停 + 补偿 + 重新规划

安全原则：
    1. 鉴权是代码逻辑，不是 LLM 的逻辑
    2. 系统提示词只做约束，不当安全边界
    3. 关键资源必须靠服务端鉴权
    4. LLM 无法绕过 PermissionChecker
"""

from .tools import (
    PermissionChecker,
    PermissionCache,
    PermissionVersionTracker,
    PermissionVersionChanged,
    create_tools,
    get_permission_cache,
    invalidate_user_permissions,
)

__all__ = [
    "PermissionChecker",
    "PermissionCache",
    "PermissionVersionTracker",
    "PermissionVersionChanged",
    "create_tools",
    "get_permission_cache",
    "invalidate_user_permissions",
]
