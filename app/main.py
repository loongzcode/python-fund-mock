"""FastAPI应用创建入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  导入实体后SQLAlchemy才能发现全部表。
from app.api import router
from app.config import Settings
from app.database import Base, create_database_engine, create_session_factory
from app.services.task_service import AsyncTaskWorker


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建应用；测试可以传入临时数据库配置。"""

    app_settings = settings or Settings()
    engine = create_database_engine(app_settings.database_url)
    session_factory = create_session_factory(engine)
    worker = AsyncTaskWorker(session_factory, app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # 本地学习默认自动建表；生产部署建议由Alembic迁移控制表结构。
        if app_settings.auto_create_tables:
            Base.metadata.create_all(engine)
        if app_settings.start_task_worker:
            worker.start()
        try:
            yield
        finally:
            worker.stop()
            engine.dispose()

    app = FastAPI(
        title="多资金方信贷接口 Mock 服务",
        version="1.0.0",
        description="当前实现苏商银行产品选定的26个HTTP接口。",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.task_worker = worker
    app.include_router(router)
    return app


# uvicorn app.main:app 启动时加载的默认应用实例。
app = create_app()

