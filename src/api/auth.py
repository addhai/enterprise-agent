"""
用户认证 API — 注册、登录、获取当前用户信息

用户/角色数据持久化到数据库（Postgres / SQLite，见 src/db/）。
password 用 bcrypt 哈希；会话 token 用 JWT（无状态，HS256，支持多副本部署，重启不失效）。
"""
import os
import time
import uuid
import hashlib
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, Field

# bcrypt 用于安全的密码哈希（替代不安全的 SHA-256）
import bcrypt

# JWT（无状态 token，支持多副本部署）
from src.config import settings
from src.api.jwt_utils import (
    create_access_token as _jwt_create,
    decode_token as _jwt_decode,
    JWTExpired,
    JWTInvalid,
)

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.models.common import UserRole, UserStatus
from src.db.repositories import (
    user_get_by_username,
    user_get_by_id,
    user_create,
    user_update,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


# ====================================================================
# 存储（Postgres / SQLite 文件，由 src.db.engine 统一切换）
# ====================================================================

# 会话 token 改为无状态 JWT（见 _get_user_by_token），不再依赖进程内字典，
# 因此支持多副本 / 多进程部署；用户 / 角色等业务数据已落库持久化。


def hash_password(password: str) -> str:
    """使用bcrypt哈希密码"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码（优先bcrypt，兼容旧版SHA-256哈希）

    兼容逻辑：如果bcrypt验证失败，尝试旧版SHA-256验证，
    用于平滑迁移已存在的SHA-256用户数据。
    """
    # 优先尝试 bcrypt 验证
    try:
        if bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8')):
            return True
    except Exception:
        # hashed_password 不是合法的 bcrypt 哈希（可能是旧版 SHA-256），继续尝试兼容验证
        pass
    # 兼容旧版 SHA-256 哈希验证
    if _legacy_sha256_verify(plain_password, hashed_password):
        return True
    return False


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


def _get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """根据用户名查找用户（从 users 表）"""
    return user_get_by_username(username)


def _get_user_by_token(token: str) -> Optional[Dict[str, Any]]:
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


def _to_user_response(u: Dict[str, Any]) -> UserResponse:
    """把 DB 用户 dict 转成 UserResponse"""
    return UserResponse(
        user_id=u["user_id"],
        username=u["username"],
        avatar=u.get("avatar", (u["username"][0].upper() if u["username"] else "?")),
        role=u.get("role", "agent"),
        status=u.get("status", "active"),
        email=u.get("email"),
        department=u.get("department"),
        created_at=u.get("created_at", 0.0),
    )


# ====================================================================
# Pydantic 模型
# ====================================================================

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    email: Optional[str] = Field(None, description="邮箱")
    department: Optional[str] = Field(None, description="部门")


class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class UserResponse(BaseModel):
    user_id: str
    username: str
    avatar: str
    role: str
    status: str
    email: Optional[str] = None
    department: Optional[str] = None
    created_at: float


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


# ====================================================================
# 依赖注入：获取当前用户
# ====================================================================

async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """获取当前登录用户（需要 Bearer token）"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证令牌")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="认证令牌格式错误")
    
    token = authorization[7:]
    user = _get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="认证令牌无效或已过期")
    
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

    # 检查用户名是否已存在
    if _get_user_by_username(username):
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 创建用户（落库）
    user_id = str(uuid.uuid4())
    now = time.time()
    user = user_create({
        "user_id": user_id,
        "username": username,
        "password_hash": _hash_password(password),
        "avatar": _get_avatar(username),
        "created_at": now,
        "is_admin": False,
        "role": UserRole.AGENT.value,
        "status": UserStatus.ACTIVE.value,
        "email": request.email or f"{username}@enterprise.local",
        "department": request.department or "未分配",
    })

    # 生成无状态 JWT（sub = user_id）
    token = _jwt_create(user_id, settings.jwt_secret, settings.access_token_expire_hours)

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

    # 查找用户
    user = _get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 验证密码（支持bcrypt，兼容旧版SHA-256）
    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

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
    token = _jwt_create(user["user_id"], settings.jwt_secret, settings.access_token_expire_hours)

    logger.info("User logged in: user_id=%s, username=%s, role=%s", user["user_id"], username, user.get("role"))

    return LoginResponse(token=token, user=_to_user_response(user))


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取当前用户信息
    
    需要在 Authorization header 中提供 Bearer token
    """
    return _to_user_response(current_user)


# 默认管理员账号（admin / agent / viewer）在 src/api/server.py 启动时通过
# src/db/init.py -> src/db/seed.py 写入数据库，无需在 import 时初始化。
