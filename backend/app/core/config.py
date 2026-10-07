"""应用配置。

配置只从环境变量与 `backend/.env` 读取，环境变量统一带 `JOBARK_` 前缀：仓库根目录的 `.env`
由 `compose.yaml` 使用（`POSTGRES_*`），两者命名空间分离，避免把数据库凭据误读成应用配置。
所有字段都有默认值，因此缺少 `.env` 时仍可直接启动，便于新环境自举。
"""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
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
    # 仅供排查 SQL 语句使用；数据库引擎始终隐藏绑定参数，避免正文和个人信息进入日志。
    database_echo: bool = False
    # 已废弃：旧环境变量保存的大模型服务地址与令牌。字段名沿用历史命名（gateway 为内部实现名，
    # 非用户可见术语）；仅为不破坏既有 `.env` 而保留，任何代码都不再读取它们，
    # 也永远不得优先于数据库中的默认模型配置（见 ADR 0004）。
    ai_gateway_url: str = ""
    ai_gateway_token: SecretStr = SecretStr("")
    # 服务商 API Key 的可逆加密根密钥；只允许 LOCAL 环境缺省使用开发默认值。
    # 根密钥必须留在数据库之外：数据库泄露时密文仍不可读，测试/生产缺失时安全失败。
    ai_credential_encryption_key: SecretStr = SecretStr("")
    ai_timeout_seconds: float = Field(default=30, gt=0, le=120)
    company_search_url: str = ""
    company_search_token: SecretStr = SecretStr("")
    company_search_name: str = "独立公司公开搜索服务"
    company_search_queries: int = Field(default=6, ge=1, le=6)
    company_search_sources: int = Field(default=8, ge=1, le=8)
    company_search_timeout: float = Field(default=15, gt=0, le=15)
    company_research_timeout: float = Field(default=90, gt=0, le=90)
    # 诊断开关：把大模型返回的 JSON 原文写入日志，用于本地排查候选为何缺失、被清空或被改写。
    # 默认关闭，且禁止在 prod 开启（见下方 validator）：模型输出可能包含简历里的姓名、
    # 联系方式与工作经历，常规日志与响应都不得承载这些内容。
    ai_log_model_output: bool = False
    # 临时开发夹具：用内置样例简历与固定抽取结果替代真实大模型调用，便于本地联调导入流程。
    # 默认关闭，仅 local/test 生效；夹具数据与样例文本自洽，不放宽任何校验（见 modules/profile/import_fixture.py）。
    profile_import_fixture: bool = False
    # 跨域白名单，默认空表示完全不挂载 CORS 中间件。
    # 开发期前端通过 Vite 代理使用相对路径访问后端（同源），生产同源部署，都不需要 CORS；
    # 只有前后端确实分离到不同源时才按环境显式启用，环境变量写法为逗号分隔，例如
    # JOBARK_CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
    # 用 NoDecode 关闭 pydantic-settings 对复杂字段的 JSON 解析，避免逗号分隔写法直接报错。
    cors_allowed_origins: Annotated[list[str], NoDecode] = []

    @model_validator(mode="after")
    def _forbid_dev_switches_in_prod(self) -> Settings:
        """禁止在生产环境开启仅供本地调试的开关。

        返回:
            Settings: 校验通过的自身实例。

        异常:
            ValueError: `prod` 环境开启任一调试开关时抛出。

        注意:
            `ai_log_model_output` 会把个人信息写进日志，`profile_import_fixture` 会用内置样例数据
            替代真实抽取。让不安全配置在**启动时**直接失败，比"开着了但没人注意"更安全。
        """
        if self.app_env is AppEnv.PROD:
            enabled = [
                name
                for name, value in (
                    ("ai_log_model_output", self.ai_log_model_output),
                    ("profile_import_fixture", self.profile_import_fixture),
                )
                if value
            ]
            if enabled:
                raise ValueError(f"{'、'.join(enabled)} 仅允许在 local/test 环境用于调试；生产环境禁止开启。")
        return self

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

    @field_validator("company_search_url")
    @classmethod
    def _safe_search_endpoint(cls, value: str) -> str:
        """配置读接口会显示端点；禁止把凭据/查询令牌写在 URL 内。"""
        if value:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("公司搜索端点必须为不含凭据、查询或片段的 HTTPS URL。")
        return value


@lru_cache
def get_settings() -> Settings:
    """返回进程级配置单例。

    返回:
        Settings: 由环境变量与 `.env` 解析出的配置；重复调用返回同一实例。
    """
    return Settings()
