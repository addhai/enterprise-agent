"""
用户认证 API — 注册、登录、获取当前用户信息

使用内存存储用户数据（简单起见，用 dict），password 用 bcrypt 哈希
token 用简单的随机字符串 + 用户信息映射
"""
import os
import time
import uuid
import secrets
import hashlib
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, Field

# bcrypt 用于安全的密码哈希（替代不安全的 SHA-256）
import bcrypt

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from src.models.common import UserRole, UserStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


# ====================================================================
# 内存存储（简单起见）
# ====================================================================

_users: Dict[str, Dict[str, Any]] = {}
_tokens: Dict[str, str] = {}


# 初始化默认管理员账号
def _init_default_admin():
    """创建默认超级管理员账号"""
    admin_id = "admin-default"
    if admin_id not in _users:
        now = time.time()
        _users[admin_id] = {
            "user_id": admin_id,
            "username": "admin",
            "password_hash": _hash_password("admin123"),
            "avatar": "A",
            "created_at": now,
            "role": UserRole.SUPER_ADMIN.value,
            "status": UserStatus.ACTIVE.value,
            "is_admin": True,
            "email": "admin@enterprise.local",
            "department": "系统管理部",
        }
        logger.info("Default admin account created: username=admin password=admin123")

    agent_id = "agent-default"
    if agent_id not in _users:
        now = time.time()
        _users[agent_id] = {
            "user_id": agent_id,
            "username": "agent",
            "password_hash": _hash_password("agent123"),
            "avatar": "A",
            "created_at": now,
            "role": UserRole.AGENT.value,
            "status": UserStatus.ACTIVE.value,
            "is_admin": False,
            "email": "agent@enterprise.local",
            "department": "客服部",
        }
        logger.info("Default agent account created: username=agent password=agent123")

    viewer_id = "viewer-default"
    if viewer_id not in _users:
        now = time.time()
        _users[viewer_id] = {
            "user_id": viewer_id,
            "username": "viewer",
            "password_hash": _hash_password("viewer123"),
            "avatar": "V",
            "created_at": now,
            "role": UserRole.VIEWER.value,
            "status": UserStatus.ACTIVE.value,
            "is_admin": False,
            "email": "viewer@enterprise.local",
            "department": "市场部",
        }
        logger.info("Default viewer account created: username=viewer password=viewer123")


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


def _generate_token() -> str:
    """生成随机 token"""
    return secrets.token_hex(32)


def _get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """根据用户名查找用户"""
    for user in _users.values():
        if user["username"] == username:
            return user
    return None


def _get_user_by_token(token: str) -> Optional[Dict[str, Any]]:
    """根据 token 查找用户"""
    user_id = _tokens.get(token)
    if not user_id:
        return None
    return _users.get(user_id)


def _get_avatar(username: str) -> str:
    """生成首字母头像（使用用户名首字母的 emoji 风格）"""
    if not username:
        return "👤"
    first_char = username[0].upper()
    return first_char


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

    # 创建用户
    user_id = str(uuid.uuid4())
    now = time.time()
    user = {
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
    }
    _users[user_id] = user

    # 生成 token
    token = _generate_token()
    _tokens[token] = user_id

    logger.info("User registered: user_id=%s, username=%s", user_id, username)

    return LoginResponse(
        token=token,
        user=UserResponse(
            user_id=user["user_id"],
            username=user["username"],
            avatar=user["avatar"],
            role=user.get("role", "agent"),
            status=user.get("status", "active"),
            email=user.get("email"),
            department=user.get("department"),
            created_at=user["created_at"],
        ),
    )


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
        user["password_hash"] = hash_password(password)
        logger.info("Password hash upgraded to bcrypt for user: %s", user["user_id"])

    # 检查用户状态
    if user.get("status") == UserStatus.SUSPENDED.value:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    # 生成新 token
    token = _generate_token()
    _tokens[token] = user["user_id"]

    logger.info("User logged in: user_id=%s, username=%s, role=%s", user["user_id"], username, user.get("role"))

    return LoginResponse(
        token=token,
        user=UserResponse(
            user_id=user["user_id"],
            username=user["username"],
            avatar=user["avatar"],
            role=user.get("role", "agent"),
            status=user.get("status", "active"),
            email=user.get("email"),
            department=user.get("department"),
            created_at=user["created_at"],
        ),
    )


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取当前用户信息
    
    需要在 Authorization header 中提供 Bearer token
    """
    return UserResponse(
        user_id=current_user["user_id"],
        username=current_user["username"],
        avatar=current_user["avatar"],
        role=current_user.get("role", "agent"),
        status=current_user.get("status", "active"),
        email=current_user.get("email"),
        department=current_user.get("department"),
        created_at=current_user["created_at"],
    )


# 初始化默认管理员账号（放在所有依赖函数定义之后）
_init_default_admin()
