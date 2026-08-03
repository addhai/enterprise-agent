"""数据库 engine 工厂 — 支持 PostgreSQL 与 SQLite 自动回退

- 生产（docker compose）连 Postgres
- 本机/测试无 Postgres 时，storage_backend=auto 自动回退到 SQLite 文件（零安装持久化）
"""
from __future__ import annotations

import logging
import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# 强制 psycopg2 使用 UTF-8，解决 Windows 中文系统 GBK 编码冲突
os.environ.setdefault("PGCLIENTENCODING", "UTF8")
os.environ.setdefault("PYTHONUTF8", "1")

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
    """保证 Postgres URL 不含非 ASCII 污染，并准备通过 connect_args 强制 UTF-8。

    不再用 URL query ?client_encoding=utf8，也不在 connect_args['options'] 里传
    '-c client_encoding=UTF8'（libpq 在 Windows 中文系统会用 ANSI 代码页编码
    options 字符串）。真正的 client_encoding 在 _pg_connect_args 中以关键字
    参数形式传给 psycopg2.connect()，可绕过该问题。
    """
    url = _clean_url(url)
    if not (url.startswith("postgresql") or url.startswith("postgres")):
        return url
    # 如果 URL 里已经带 client_encoding query，先剥掉（避免重复/冲突）
    p = urlparse(url)
    qs = parse_qs(p.query)
    qs.pop("client_encoding", None)
    p = p._replace(query=urlencode(qs, doseq=True))
    return urlunparse(p)


def _pg_connect_args(url: str) -> dict:
    """Postgres 连接参数：超时 + 强制 UTF-8 编码（绕开 Windows GBK 代码页 bug）。"""
    if url.startswith("postgresql") or url.startswith("postgres"):
        return {"connect_timeout": 3, "client_encoding": "utf8"}
    return {}


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
        logger.warning("PostgreSQL not reachable: %s", e)
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
