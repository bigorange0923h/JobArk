"""应用配置。

配置只从环境变量与 `backend/.env` 读取，环境变量统一带 `JOBARK_` 前缀：仓库根目录的 `.env`
由 `compose.yaml` 使用（`POSTGRES_*`），两者命名空间分离，避免把数据库凭据误读成应用配置。
所有字段都有默认值，因此缺少 `.env` 时仍可直接启动，便于新环境自举。
"""

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class AppEnv(StrEnum):
    """运行环境标识。"""

    LOCAL = "local"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    """运行期配置。

    环境变量名 = `JOBARK_` + 字段名大写，例如 `JOBARK_LOG_LEVEL`。
    `.env` 按进程工作目录解析，因此后端应在 `backend/` 目录下启动。
    """

    model_config = SettingsConfigDict(
        env_prefix="JOBARK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "JobArk"
    app_env: AppEnv = AppEnv.LOCAL
    log_level: LogLevel = "INFO"
    # 业务领域路由的统一挂载前缀；/health 等运维接口不带版本，便于探针长期稳定引用。
    api_v1_prefix: str = "/api/v1"


@lru_cache
def get_settings() -> Settings:
    """返回进程级配置单例。

    返回:
        Settings: 由环境变量与 `.env` 解析出的配置；重复调用返回同一实例。
    """
    return Settings()
