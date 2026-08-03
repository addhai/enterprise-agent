"""数据库初始化：建表 + seed 默认数据

在应用启动时（src/api/server.py 的 startup）调用一次。
"""
from __future__ import annotations

import logging

from src.db.base import Base
from src.db.engine import _decode_pg_error, get_engine

logger = logging.getLogger(__name__)


def init_db() -> None:
    """创建所有表（基于 Base.metadata），并 seed 默认账号/演示数据。"""
    # 务必先导入所有模型，确保它们注册到 Base.metadata
    from src.db import models  # noqa: F401
    from src.db import seed as db_seed

    engine = get_engine()
    logger.info("Creating database tables (if not exist)...")
    try:
        Base.metadata.create_all(engine)
        logger.info("Database tables ready.")
    except Exception as e:
        logger.warning("Database init failed (non-fatal): %s", _decode_pg_error(e))
        return

    try:
        db_seed.seed_defaults()
    except Exception as e:
        logger.warning("DB seed_defaults failed (non-fatal): %s", _decode_pg_error(e))
