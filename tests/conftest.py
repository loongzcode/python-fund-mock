"""pytest公共测试环境。"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """每条测试使用独立SQLite文件，避免测试数据互相影响。"""

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'fund_mock_test.db'}",
        delayed_success_millis=0,
        auto_create_tables=True,
        start_task_worker=False,
    )
    app = create_app(settings)
    # TestClient作为上下文管理器使用时，FastAPI的lifespan才会执行。
    with TestClient(app) as test_client:
        yield test_client

