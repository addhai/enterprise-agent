"""数据库 engine 工厂 — 支持 PostgreSQL 与 SQLite 自动回退

- 生产（docker compose）连 Postgres
- 本机/测试无 Postgres 时，storage_backend=auto 自动回退到 SQLite 文件（零安装持久化）
"""
from __future__ import annotations

import logging
import os

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
        from urllib.parse import urlparse
        p = urlparse(url)
        if p.password:
            netloc = p.hostname or ""
            if p.port:
                netloc += f":{p.port}"
            return url.replace(f"{p.username}:{p.password}@", f"{p.username}:***@")
    except Exception:
        pass
    return url


def _pg_connect_args(url: str) -> dict:
    """Postgres 连接参数：强制 UTF-8 编码（解决 Windows 中文系统 GBK 编码冲突）"""
    if url.startswith("postgresql") or url.startswith("postgres"):
        return {
            "connect_timeout": 3,
            "options": "-c client_encoding=UTF8",
        }
    return {}


def _pg_reachable(url: str) -> bool:
    """探测 Postgres 是否可达（3 秒超时）"""
    try:
        connect_args = _pg_connect_args(url)
        probe = create_engine(url, pool_pre_ping=False, connect_args=connect_args)
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
        probe.dispose()
        return True
    except Exception as e:
        logger.warning("PostgreSQL not reachable: %s", e)
        return False


def _resolve_url() -> str:
    """根据 storage_backend 决定最终连接串"""
    raw = settings.database_url
    backend = getattr(settings, "storage_backend", "auto")
    if backend == "sqlite":
        return raw if raw.startswith("sqlite") else "sqlite:///./agent.db"
    if backend == "postgres":
        return raw
    # auto
    if raw.startswith("sqlite"):
        return raw
    if _pg_reachable(raw):
        return raw
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
