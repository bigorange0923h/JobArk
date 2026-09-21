"""应用配置。

配置只从环境变量与 `backend/.env` 读取，环境变量统一带 `JOBARK_` 前缀：仓库根目录的 `.env`
由 `compose.yaml` 使用（`POSTGRES_*`），两者命名空间分离，避免把数据库凭据误读成应用配置。
所有字段都有默认值，因此缺少 `.env` 时仍可直接启动，便于新环境自举。
"""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    # 异步驱动固定为 asyncpg：数据访问范式在 ADR 0002 中确定，不做同步/异步混用。
    # 默认值是本地开发占位串，密码必须与仓库根目录 .env 的 POSTGRES_PASSWORD 一致；
    # 未配置时服务仍可启动，但首次查询会以明确的认证失败暴露问题。
    database_url: str = "postgresql+asyncpg://jobark_app:jobark_app@127.0.0.1:5432/jobark"
    # 仅供本地排查 SQL 使用；生产环境开启会把语句与参数写入日志。
    database_echo: bool = False
    # 跨域白名单，默认空表示完全不挂载 CORS 中间件。
    # 开发期前端通过 Vite 代理使用相对路径访问后端（同源），生产同源部署，都不需要 CORS；
    # 只有前后端确实分离到不同源时才按环境显式启用，环境变量写法为逗号分隔，例如
    # JOBARK_CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
    # 用 NoDecode 关闭 pydantic-settings 对复杂字段的 JSON 解析，避免逗号分隔写法直接报错。
    cors_allowed_origins: Annotated[list[str], NoDecode] = []

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """把逗号分隔的跨域白名单拆分为列表。

        参数:
            value: 环境变量或构造参数传入的原始值。

        返回:
            object: 字符串输入拆分为去空白的列表，其他输入原样返回交由 pydantic 校验。

        注意:
            空白项会被丢弃，避免写成 `a,,b` 时把空串当成合法来源（空来源等价于任意来源）。
        """
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """返回进程级配置单例。

    返回:
        Settings: 由环境变量与 `.env` 解析出的配置；重复调用返回同一实例。
    """
    return Settings()
