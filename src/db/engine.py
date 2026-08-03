"""数据库 engine 工厂 — 支持 PostgreSQL 与 SQLite 自动回退

- 生产（docker compose）连 Postgres
- 本机/测试无 Postgres 时，storage_backend=auto 自动回退到 SQLite 文件（零安装持久化）
"""
from __future__ import annotations

import logging
import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# 强制 psycopg2/libpq 使用 UTF-8 客户端编码 + 英文 locale，解决 Windows
# 中文系统 GBK 编码冲突。在 src/api/server.py 入口已经设置过；这里再次
# 强制设置作为兜底，防止模块被单独导入时（如测试、脚本）遗漏。
os.environ["PGCLIENTENCODING"] = "UTF8"
os.environ["PYTHONUTF8"] = "1"
# LC_ALL/LC_MESSAGES 控制 libpq 客户端自身错误信息语言，避免中文 GBK 报错。
os.environ["LC_ALL"] = "C"
os.environ["LC_MESSAGES"] = "C"

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.config import settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None


def _mask(url: str) -> str:
    """日志中隐藏密码"""
    try:
        p = urlparse(url)
        if p.password:
            netloc = p.hostname or ""
            if p.port:
                netloc += f":{p.port}"
            return url.replace(f"{p.username}:{p.password}@", f"{p.username}:***@")
    except Exception:
        pass
    return url


def _clean_url(url: str) -> str:
    """清理 URL：去掉行内注释、首尾空白，防止 .env / 环境变量污染。"""
    if not isinstance(url, str):
        url = str(url)
    # 去掉 # 开头的行内注释（dotenv 本应做，但环境变量或某些编辑器会带进来）
    url = url.split("#", 1)[0].strip()
    return url


def _ensure_pg_encoding(url: str) -> str:
    """保证 Postgres URL 不含非 ASCII 污染，并在 query 中强制 UTF-8 + 英文报错。

    在 URL query 中追加 client_encoding=utf8 与 options=-c lc_messages=C，
    让 libpq 在连接握手阶段就把这两个参数发给 PostgreSQL，尽量让服务器在
    返回连接错误时也使用英文（全 ASCII），避免 Windows 中文系统用 GBK 返回
    错误信息导致 psycopg2 解码崩溃（byte 0xd6）。

    同时在 _pg_connect_args 中仍以关键字参数形式重复设置，作为双重兜底。
    """
    url = _clean_url(url)
    if not (url.startswith("postgresql") or url.startswith("postgres")):
        return url
    p = urlparse(url)
    qs = parse_qs(p.query)
    # 去掉可能冲突的旧值，再用列表形式追加（urlencode(doseq=True) 兼容多值）
    qs.pop("client_encoding", None)
    qs.pop("options", None)
    qs["client_encoding"] = ["utf8"]
    qs["options"] = ["-c lc_messages=C"]
    p = p._replace(query=urlencode(qs, doseq=True))
    return urlunparse(p)


def _pg_connect_args(url: str) -> dict:
    """Postgres 连接参数：超时 + 强制 UTF-8 编码 + 强制英文报错（双重兜底）。"""
    if url.startswith("postgresql") or url.startswith("postgres"):
        return {
            "connect_timeout": 3,
            "client_encoding": "utf8",
            "options": "-c lc_messages=C",
        }
    return {}


def _decode_pg_error(exc: Exception) -> str:
    """把 PostgreSQL 连接异常转换成可读字符串，兼容 Windows GBK 错误信息。

    psycopg2 在 Windows 中文系统下可能把 GBK 编码的中文错误信息按 UTF-8 解码，
    直接抛出 UnicodeDecodeError 而不是 OperationalError。本函数优先尝试 GBK
    解码原始 bytes，让用户看到真实的数据库错误（如密码错、数据库不存在）。
    """
    # 1) 如果异常对象本身可 str，先拿到文本
    msg = str(exc)
    # 2) 异常可能带有 .args，其中包含原始 bytes
    raw: bytes | None = None
    for arg in getattr(exc, "args", ()):
        if isinstance(arg, bytes):
            raw = arg
            break
    if raw is None:
        return msg
    # 3) 尝试 GBK 解码；失败则回退 latin1（单字节不会丢信息）
    for enc in ("gbk", "utf-8", "latin1"):
        try:
            decoded = raw.decode(enc)
            return f"{msg} (decoded with {enc}: {decoded})"
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
    return msg


def _pg_reachable(url: str) -> bool:
    """探测 Postgres 是否可达（3 秒超时）"""
    try:
        url_with_encoding = _ensure_pg_encoding(url)
        connect_args = _pg_connect_args(url_with_encoding)
        probe = create_engine(url_with_encoding, pool_pre_ping=False, connect_args=connect_args)
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
        probe.dispose()
        return True
    except Exception as e:
        logger.warning("PostgreSQL not reachable: %s", _decode_pg_error(e))
        return False


def _resolve_url() -> str:
    """根据 storage_backend 决定最终连接串"""
    raw = _clean_url(settings.database_url)
    logger.debug("Resolved raw database_url (masked): %s", _mask(raw))
    backend = getattr(settings, "storage_backend", "auto")
    if backend == "sqlite":
        return raw if raw.startswith("sqlite") else "sqlite:///./agent.db"
    if backend == "postgres":
        return _ensure_pg_encoding(raw)
    # auto
    if raw.startswith("sqlite"):
        return raw
    if _pg_reachable(raw):
        return _ensure_pg_encoding(raw)
    logger.warning(
        "PostgreSQL unreachable; falling back to SQLite file ./agent.db for local persistence"
    )
    return "sqlite:///./agent.db"


def get_engine() -> Engine:
    """懒加载并缓存 engine 单例"""
    global _engine
    if _engine is None:
        url = _resolve_url()
        connect_args: dict = {}
        poolclass = None
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
            # 内存库必须用 StaticPool：每个连接会拿到独立的 ':memory:' 实例，
            # 否则不同 session 看不到彼此写入的数据。生产用文件/Postgres 不受影响。
            if url == "sqlite:///:memory:":
                from sqlalchemy.pool import StaticPool

                poolclass = StaticPool
        elif url.startswith("postgresql") or url.startswith("postgres"):
            connect_args = _pg_connect_args(url)
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            future=True,
            connect_args=connect_args,
            poolclass=poolclass,
        )
        logger.info("DB engine ready: %s", _mask(url))
    return _engine


def dispose_engine() -> None:
    """释放 engine（测试 / 关闭时使用）"""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
