"""PostgreSQL / SQLite 持久化层

提供统一的 SQLAlchemy 同步 ORM 基础设施：
    - Base           声明基类
    - get_engine()   根据 storage_backend 解析并缓存 engine（PG / SQLite 自动回退）
    - db_session()   同步 session 上下文管理器（供各 repository 直接使用）
    - init_db()      建表 + seed 默认数据（在应用启动时调用）

设计目标：
    - 生产（docker compose）连 Postgres；本机无 PG 时自动回退 SQLite 文件，零安装体验持久化。
    - 对现有业务代码的侵入最小：repository 函数直接接收 / 返回现有 Pydantic 模型或 dict。
"""
