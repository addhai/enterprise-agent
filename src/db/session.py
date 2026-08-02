"""同步 DB session 上下文管理器

供各 repository 与业务代码使用（同步阻塞，对 demo 规模的单进程服务足够；
与现有 get_retriever() 等同步调用的风格一致）。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session, sessionmaker

from src.db.engine import get_engine

_SessionLocal: sessionmaker | None = None


def get_session_local() -> sessionmaker:
    """懒加载 sessionmaker 单例"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, autocommit=False, future=True
        )
    return _SessionLocal


@contextmanager
def db_session() -> Iterator[Session]:
    """同步 session 上下文管理器，自动 commit/rollback/close。"""
    SessionLocal = get_session_local()
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
