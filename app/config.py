"""读取环境变量并生成应用配置。

初学者可以把这个文件理解为 Java 项目里的 ``application.yml``。
代码的其他部分只读取 ``Settings``，不直接到处调用 ``os.getenv``，这样测试时
可以很方便地传入一套临时配置。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服务运行所需的全部配置。"""

    # SQLite 适合本地学习；生产环境通过环境变量替换成 MySQL 连接地址。
    database_url: str = "sqlite:///./data/fund_mock.db"
    default_scenario: str = "SUCCESS"
    delayed_success_millis: int = 2_000
    task_scan_interval_millis: int = 500
    callback_max_retries: int = 5
    credit_callback_url: str | None = None
    loan_callback_url: str | None = None
    repayment_callback_url: str | None = None
    auto_create_tables: bool = True
    start_task_worker: bool = True

    model_config = SettingsConfigDict(
        env_prefix="FUND_MOCK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

