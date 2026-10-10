"""
用户认证 API — 注册、登录、获取当前用户信息

用户/角色数据持久化到数据库（Postgres / SQLite，见 src/db/）。
password 用 bcrypt 哈希；会话 token 用 JWT（无状态，HS256，
支持多副本部署，重启不失效）。
"""

# 关键：使所有注解延迟求值（字符串化），与 Python 3.11/3.13
# 的「注解即时求值」语义兼容。
# 否则下面 `_to_user_response(...) -> UserResponse` 会在模块加载时
# 引用尚未定义的 UserResponse 而 NameError
# （Python 3.14 已改为延迟求值，所以本地能跑、CI 3.11 崩）。
from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from typing import Any

# bcrypt 用于安全的密码哈希（替代不安全的 SHA-256）
import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.jwt_utils import (
    JWTExpired,
    JWTInvalid,
)
from src.api.jwt_utils import (
    create_access_token as _jwt_create,
)
from src.api.jwt_utils import (
    decode_token as _jwt_decode,
)

# JWT（无状态 token，支持多副本部署）
from src.config import settings

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.api.login_guard import get_login_guard
from src.db.repositories import (
    user_create,
    user_get_by_id,
    user_get_by_username,
    user_update,
)

# seed 默认账号的「用户名 → 出厂密码」映射，作为默认密码检测的唯一来源，
# 避免与 src/db/seed.py 两处维护漂移。
from src.db.seed import DEFAULT_USERS as _DEFAULT_SEED_USERS
from src.models.common import UserRole, UserStatus

_DEFAULT_PASSWORD_MAP = {u["username"]: u["password"] for u in _DEFAULT_SEED_USERS}

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


# ====================================================================
# 存储（Postgres / SQLite 文件，由 src.db.engine 统一切换）
# ====================================================================

# 会话 token 改为无状态 JWT（见 _get_user_by_token），不再依赖进程内字典，
# 因此支持多副本 / 多进程部署；用户 / 角色等业务数据已落库持久化。


def hash_password(password: str) -> str:
    """使用bcrypt哈希密码"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码（优先bcrypt，兼容旧版SHA-256哈希）

    兼容逻辑：如果bcrypt验证失败，尝试旧版SHA-256验证，
    用于平滑迁移已存在的SHA-256用户数据。
    """
    # 优先尝试 bcrypt 验证。非 bcrypt 哈希会抛 ValueError/TypeError，
    # 属正常兼容路径（可能是旧版 SHA-256），落到下方兼容验证，不打日志避免噪音。
    try:
        if bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        ):
            return True
    except Exception:  # noqa: S110 - 哈希格式不匹配是预期分支，静默回退
        pass
    # 兼容旧版 SHA-256 哈希验证
    return _legacy_sha256_verify(plain_password, hashed_password)


def _legacy_sha256_hash(password: str) -> str:
    """旧版 SHA-256 哈希（仅用于兼容已存在的用户数据，不再用于新密码）"""
    salt = "enterprise-agent-salt-2024"
    return hashlib.sha256((salt + password).encode()).hexdigest()


def _legacy_sha256_verify(plain_password: str, hashed_password: str) -> bool:
    """旧版 SHA-256 验证"""
    return _legacy_sha256_hash(plain_password) == hashed_password


def _needs_upgrade(hashed_password: str) -> bool:
    """判断密码哈希是否需要升级为bcrypt（即仍是旧版SHA-256）"""
    return not hashed_password.startswith("$2")


def _hash_password(password: str) -> str:
    """密码哈希（兼容旧调用入口，内部使用bcrypt）"""
    return hash_password(password)


def is_default_password(user: dict[str, Any]) -> bool:
    """账号是否仍在使用 seed 出厂密码（P0-6）。

    判定方式无需改表加字段：用户名在 seed 清单内、且当前哈希能验通出厂密码。
    用户一旦改密，哈希即不再匹配出厂密码，标志自动消失。
    """
    candidate = _DEFAULT_PASSWORD_MAP.get(user.get("username"))
    if not candidate:
        return False
    try:
        return verify_password(candidate, user.get("password_hash", ""))
    except Exception:
        return False


def _get_user_by_username(username: str) -> dict[str, Any] | None:
    """根据用户名查找用户（从 users 表）"""
    return user_get_by_username(username)


def _get_user_by_token(token: str) -> dict[str, Any] | None:
    """根据 JWT 查找用户（验签 + 过期校验，再从库取最新用户数据）"""
    try:
        payload = _jwt_decode(token, settings.jwt_secret)
    except JWTExpired:
        return None
    except JWTInvalid:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return user_get_by_id(user_id)


def _get_avatar(username: str) -> str:
    """生成首字母头像（使用用户名首字母的 emoji 风格）"""
    if not username:
        return "👤"
    first_char = username[0].upper()
    return first_char


def _to_user_response(u: dict[str, Any]) -> UserResponse:
    """把 DB 用户 dict 转成 UserResponse"""
    return UserResponse(
        user_id=u["user_id"],
        username=u["username"],
        avatar=u.get("avatar", (u["username"][0].upper() if u["username"] else "?")),
        role=u.get("role", "agent"),
        status=u.get("status", "active"),
        tenant_id=u.get("tenant_id", "default"),
        email=u.get("email"),
        department=u.get("department"),
        created_at=u.get("created_at", 0.0),
        must_change_password=is_default_password(u),
    )


# ====================================================================
# Pydantic 模型
# ====================================================================


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    email: str | None = Field(None, description="邮箱")
    department: str | None = Field(None, description="部门")
    tenant_id: str = Field(
        default="default", description="归属租户ID（注册时归属，决定数据隔离空间）"
    )


class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class UserResponse(BaseModel):
    user_id: str
    username: str
    avatar: str
    role: str
    status: str
    tenant_id: str = "default"
    email: str | None = None
    department: str | None = None
    created_at: float
    # P0-6：仍使用出厂密码时为 true，前端应引导改密
    must_change_password: bool = False


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, description="当前密码")
    new_password: str = Field(..., min_length=8, max_length=100, description="新密码")


# ====================================================================
# 依赖注入：获取当前用户
# ====================================================================

# 强制改密期间仍允许访问的路径（查自身信息、改密、登出）。
# 用路径后缀匹配，兼容 /api/v1 前缀差异。
_PASSWORD_ENFORCE_WHITELIST_SUFFIXES = (
    "/auth/me",
    "/auth/change-password",
    "/auth/logout",
)


async def get_current_user(
    authorization: str | None = Header(None),
    request: Request = None,
) -> dict[str, Any]:
    """获取当前登录用户（需要 Bearer token）"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="认证令牌格式错误")

    token = authorization[7:]
    user = _get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="认证令牌无效或已过期")

    # 停用/冻结账号的 token 在剩余有效期内也必须立即失效（P0-6）。
    # 历史状态值统一按非 active 即拒绝处理，缺字段时放行兼容旧数据。
    if user.get("status") and user["status"] != "active":
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")

    # 出厂默认密码未改时，除白名单外的业务接口一律拒绝（P0-6）。
    # 开关 settings.require_default_password_change 供现网灰度时临时豁免。
    if settings.require_default_password_change and is_default_password(user):
        path = request.url.path if request is not None else ""
        if not any(
            path.endswith(suffix) for suffix in _PASSWORD_ENFORCE_WHITELIST_SUFFIXES
        ):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "PASSWORD_CHANGE_REQUIRED",
                    "message": (
                        "账号仍在使用出厂默认密码，"
                        "请先调用 /auth/change-password 修改密码"
                    ),
                },
            )

    return user


# ====================================================================
# API 路由
# ====================================================================


@router.post("/auth/register", response_model=LoginResponse)
async def register(request: RegisterRequest):
    """用户注册

    - username: 用户名（3-50 字符）
    - password: 密码（6-100 字符）

    返回 token 和用户信息
    """
    username = request.username.strip()
    password = request.password

    # 归属租户：校验存在（防注册到不存在的租户，保证隔离空间有效）
    from src.db.repositories import DEFAULT_TENANT, tenant_exists

    tenant_id = (request.tenant_id or "").strip() or DEFAULT_TENANT
    if not tenant_exists(tenant_id):
        raise HTTPException(status_code=400, detail=f"租户不存在: {tenant_id}")

    # 检查用户名是否已存在
    if _get_user_by_username(username):
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 创建用户（落库）
    user_id = str(uuid.uuid4())
    now = time.time()
    user = user_create(
        {
            "user_id": user_id,
            "username": username,
            "password_hash": _hash_password(password),
            "avatar": _get_avatar(username),
            "created_at": now,
            "is_admin": False,
            "role": UserRole.AGENT.value,
            "status": UserStatus.ACTIVE.value,
            "tenant_id": tenant_id,
            "email": request.email or f"{username}@enterprise.local",
            "department": request.department or "未分配",
        }
    )

    # 生成无状态 JWT（sub = user_id）
    token = _jwt_create(
        user_id, settings.jwt_secret, settings.access_token_expire_hours
    )

    logger.info("User registered: user_id=%s, username=%s", user_id, username)

    return LoginResponse(token=token, user=_to_user_response(user))


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """用户登录

    - username: 用户名
    - password: 密码

    返回 token 和用户信息
    """
    username = request.username.strip()
    password = request.password
    guard = get_login_guard()

    # 爆破防护：锁定期内直接拒绝，不再查库验密（P0-6）。
    locked_seconds = guard.locked_seconds(username)
    if locked_seconds > 0:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多，账号已临时锁定，请 {locked_seconds} 秒后再试",
            headers={"Retry-After": str(locked_seconds)},
        )

    # 查找用户
    user = _get_user_by_username(username)
    if not user:
        # 对不存在的用户名同样计数，响应文案与密码错误保持一致，削弱用户名枚举
        guard.record_failure(username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 验证密码（支持bcrypt，兼容旧版SHA-256）
    if not verify_password(password, user["password_hash"]):
        fails = guard.record_failure(username)
        logger.warning(
            "Login failed: username=%s, consecutive_failures=%d", username, fails
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 登录成功，清空失败计数
    guard.record_success(username)

    # 自动升级：将旧版SHA-256哈希升级为bcrypt
    if _needs_upgrade(user["password_hash"]):
        new_hash = hash_password(password)
        user_update(user["user_id"], {"password_hash": new_hash})
        user["password_hash"] = new_hash
        logger.info("Password hash upgraded to bcrypt for user: %s", user["user_id"])

    # 检查用户状态
    if user.get("status") == UserStatus.SUSPENDED.value:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    # 生成无状态 JWT（sub = user_id）
    token = _jwt_create(
        user["user_id"], settings.jwt_secret, settings.access_token_expire_hours
    )

    logger.info(
        "User logged in: user_id=%s, username=%s, role=%s",
        user["user_id"],
        username,
        user.get("role"),
    )

    return LoginResponse(token=token, user=_to_user_response(user))


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: dict[str, Any] = Depends(get_current_user)):
    """获取当前用户信息

    需要在 Authorization header 中提供 Bearer token
    """
    return _to_user_response(current_user)


@router.post("/auth/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """修改当前登录用户密码（P0-6 默认账号强制改密的配套出口）

    - 校验旧密码，防 token 被盗后静默改密
    - 新密码至少 8 位，且不得与旧密码 / 任一种子出厂密码相同
    - 成功后旧 token 仍按原有效期自然过期；无状态 JWT 不做强制踢下线，
      多副本场景如需立即失效，应引入 token 版本号/吊销清单
    """
    user_id = current_user["user_id"]
    if not verify_password(body.old_password, current_user["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码不正确")

    new_password = body.new_password
    if new_password == body.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    if new_password in set(_DEFAULT_PASSWORD_MAP.values()):
        raise HTTPException(status_code=400, detail="新密码不能使用系统出厂默认密码")

    user_update(user_id, {"password_hash": hash_password(new_password)})
    logger.info("Password changed for user_id=%s", user_id)
    return {"ok": True, "message": "密码修改成功"}


# 默认管理员账号（admin / agent / viewer）在 src/api/server.py 启动时通过
# src/db/init.py -> src/db/seed.py 写入数据库，无需在 import 时初始化。
