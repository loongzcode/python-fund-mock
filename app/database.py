"""数据库连接和会话工厂。

SQLAlchemy 中的 ``Engine`` 管理数据库连接池，``Session`` 代表一次业务事务。
每个 HTTP 请求和每个异步任务都应使用独立 Session，不能把同一个 Session
跨线程共享。
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    """全部数据库实体类的父类。"""


def create_database_engine(database_url: str) -> Engine:
    """根据连接地址创建数据库引擎。

    SQLite 默认不允许同一个连接跨线程使用，而任务扫描器运行在后台线程，
    所以本地 SQLite 需要设置 ``check_same_thread=False``。MySQL 不需要该参数。
    """

    if database_url.startswith("sqlite"):
        # SQLite 文件所在目录不存在时，先创建目录，避免首次启动失败。
        if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
            file_name = database_url.removeprefix("sqlite:///")
            Path(file_name).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )

    return create_engine(database_url, pool_pre_ping=True, pool_recycle=1_800)


def create_session_factory(engine: Engine) -> sessionmaker:
    """创建 Session 工厂，而不是立即创建数据库会话。"""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

