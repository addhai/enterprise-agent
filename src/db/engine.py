"""数据库 engine 工厂 — 支持 PostgreSQL 与 SQLite 自动回退

- 生产（docker compose）连 Postgres
- 本机/测试无 Postgres 时，storage_backend=auto 自动回退到 SQLite 文件（零安装持久化）
"""
from __future__ import annotations

import logging
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


def _pg_reachable(url: str) -> bool:
    """探测 Postgres 是否可达（3 秒超时）"""
    try:
        probe = create_engine(url, pool_pre_ping=False, connect_args={"connect_timeout": 3})
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
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        _engine = create_engine(
            url, pool_pre_ping=True, future=True, connect_args=connect_args
        )
        logger.info("DB engine ready: %s", _mask(url))
    return _engine


def dispose_engine() -> None:
    """释放 engine（测试 / 关闭时使用）"""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
