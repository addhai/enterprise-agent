"""JWT 工具 — 标准 RFC 7519 HS256 实现，零第三方依赖。

用于 access token 的生成与校验，替代原内存 token 字典，使鉴权成为无状态（stateless），
支持多副本 / 多进程部署（任意副本都能独立验签，无需共享内存）。

算法：HS256（HMAC-SHA256）
- token 形如 ``header.payload.signature``，三段均 base64url 编码
- 签名 = HMAC-SHA256(secret, ``header.payload``)，接收方用同一 secret 复算并比对
- payload 含 ``sub``(user_id) / ``iat``(签发时间) / ``exp``(过期时间) / ``jti``(唯一 ID)
"""
import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Dict, Optional


class JWTError(Exception):
    """JWT 校验失败基类"""


class JWTExpired(JWTError):
    """token 已过期"""


class JWTInvalid(JWTError):
    """token 格式 / 签名非法"""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def encode(payload: Dict[str, Any], secret: str, algorithm: str = "HS256") -> str:
    """编码 payload 为 JWT 字符串（HS256）。"""
    if algorithm != "HS256":
        raise JWTInvalid("仅支持 HS256 算法")
    header = {"alg": "HS256", "typ": "JWT"}
    seg1 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    seg2 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{seg1}.{seg2}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    seg3 = _b64url_encode(sig)
    return f"{seg1}.{seg2}.{seg3}"


def decode_token(token: str, secret: str, algorithm: str = "HS256") -> Dict[str, Any]:
    """校验签名与过期时间，返回 payload；失败抛 JWTExpired / JWTInvalid。"""
    if algorithm != "HS256":
        raise JWTInvalid("仅支持 HS256 算法")
    try:
        seg1, seg2, seg3 = token.split(".")
    except ValueError:
        raise JWTInvalid("token 格式错误（应包含 3 段）")
    signing_input = f"{seg1}.{seg2}".encode("ascii")
    try:
        expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        sig = _b64url_decode(seg3)
    except Exception:
        raise JWTInvalid("签名段解码失败")
    if not hmac.compare_digest(expected, sig):
        raise JWTInvalid("签名校验失败")
    try:
        payload = json.loads(_b64url_decode(seg2))
    except Exception:
        raise JWTInvalid("payload 解码失败")
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp < time.time():
        raise JWTExpired("token 已过期")
    return payload


def create_access_token(
    user_id: str,
    secret: str,
    expire_hours: int = 12,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """生成 access token，payload 含 sub / iat / exp / jti，可附加自定义 claims。"""
    now = int(time.time())
    payload: Dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + int(expire_hours * 3600),
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return encode(payload, secret)
