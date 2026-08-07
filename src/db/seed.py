"""数据库层默认数据 seed

在 src/api/server.py 的 startup 调 init_db() 时执行。
默认账号密码使用与 auth.py 一致的 bcrypt 哈希。
"""
from __future__ import annotations

import bcrypt
import logging

from src.db.repositories import ensure_default_users

logger = logging.getLogger(__name__)

DEFAULT_USERS = [
    {
        "user_id": "admin-default", "username": "admin", "password": "admin123",
        "role": "super_admin", "is_admin": True, "email": "admin@enterprise.local",
        "department": "System Management",
    },
    {
        "user_id": "agent-default", "username": "agent", "password": "agent123",
        "role": "agent", "is_admin": False, "email": "agent@enterprise.local",
        "department": "Customer Service",
    },
    {
        "user_id": "viewer-default", "username": "viewer", "password": "viewer123",
        "role": "viewer", "is_admin": False, "email": "viewer@enterprise.local",
        "department": "Marketing",
    },
]

# 默认租户：单租户部署回退用，启动时确保存在（多租户运行化的根）
DEFAULT_TENANTS = [
    {"tenant_id": "default", "name": "Default Tenant", "plan": "free", "status": "active"},
]


def seed_defaults() -> None:
    defaults = []
    for u in DEFAULT_USERS:
        d = dict(u)
        d["password_hash"] = bcrypt.hashpw(
            u["password"].encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        defaults.append(d)
    ensure_default_users(defaults)
    logger.info("Default users seeded (count=%d)", len(defaults))

    # 预置 default 租户（多租户运行化的基座；其余租户经 /admin/tenants 创建）
    from src.db.repositories import ensure_default_tenants
    ensure_default_tenants(DEFAULT_TENANTS)
    logger.info("Default tenant seeded")
