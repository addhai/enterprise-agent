"""同步 DB session 上下文管理器

供各 repository 与业务代码使用（同步阻塞，对 demo 规模的单进程服务足够；
与现有 get_retriever() 等同步调用的风格一致）。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from src.db.engine import _decode_pg_error, get_engine

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
    """同步 session 上下文管理器，自动 commit/rollback/close。

    在 yield 前先 ping 一次数据库，把 Windows GBK 编码错误转换成可读信息。
    """
    SessionLocal = get_session_local()
    session: Session = SessionLocal()
    try:
        # 强制立即建立连接；若失败，把 GBK 中文错误信息解码成可读文本再抛出
        session.connection()
        yield session
        session.commit()
    except Exception as exc:
        session.rollback()
        # Windows 中文系统下 psycopg2 可能把 GBK 中文错误信息按 UTF-8 解码失败，
        # 直接抛出 UnicodeDecodeError。把它转换成可读的真实 PG 错误。
        if isinstance(exc, UnicodeDecodeError):
            raise RuntimeError(_decode_pg_error(exc)) from exc
        raise
    finally:
        session.close()
