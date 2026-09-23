"""测试夹具。

每个测试通过 `create_app` 构建独立应用实例，并挂载仅用于验证契约的探针路由。
探针路由不进入生产入口，避免为测试而在正式应用上暴露调试接口。

测试配置显式禁用 `.env` 加载，防止开发者本地配置让测试结果不可复现。
依赖数据库的测试通过环境变量 `JOBARK_TEST_DATABASE_URL` 指向独立测试库；
未设置时会被跳过，使不含 PostgreSQL 的环境仍能跑完其余测试。
"""

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import AppEnv, Settings, get_settings
from app.core.errors import ResourceNotFoundError
from app.core.responses import ApiResponse, success
from app.main import create_app

TEST_DATABASE_URL_ENV = "JOBARK_TEST_DATABASE_URL"
BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 领域表清单：清空测试数据时使用，顺序无关（TRUNCATE 带 CASCADE）。
_DOMAIN_TABLES = (
    # AI 配置表：先于其父表出现，保持"子表在前"的可读顺序。
    "ai_models",
    "ai_providers",
    "job_parse_results",
    "match_results",
    "application_events",
    "applications",
    "job_snapshots",
    "job_postings",
    "job_opportunities",
    "companies",
    "resume_version_evidences",
    "resume_drafts",
    "resume_versions",
    "resumes",
    "profile_revisions",
    "profile_preferences",
    "profile_languages",
    "profile_educations",
    "profile_projects",
    "profile_experiences",
    "profile_skills",
    "profile_evidences",
    "personal_profiles",
)


@pytest.fixture
def settings() -> Settings:
    """返回测试专用配置。

    返回:
        Settings: 固定测试环境与告警级日志，且不读取 `.env`。
    """
    # `_env_file=None` 关闭 .env 读取，避免开发者本地配置影响测试结果。
    # pydantic-settings 在运行期支持该参数，但未在生成的 __init__ 签名中声明，故需显式豁免类型检查。
    return Settings(app_env=AppEnv.TEST, log_level="WARNING", _env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """构建带契约探针路由的应用实例。

    参数:
        settings: 测试配置。

    返回:
        FastAPI: 可验证校验失败、领域异常与未捕获异常处理的应用。
    """
    application = create_app(settings)

    @application.get("/_probe/echo", response_model=ApiResponse[dict[str, str]])
    async def probe_echo(limit: int) -> ApiResponse[dict[str, str]]:
        """校验探针：`limit` 缺失或非整数时触发 422。"""
        return success({"limit": str(limit)})

    @application.get("/_probe/missing", response_model=ApiResponse[dict[str, str]])
    async def probe_missing() -> ApiResponse[dict[str, str]]:
        """领域异常探针：模拟资源不存在。"""
        raise ResourceNotFoundError("测试用的资源不存在。")

    @application.get("/_probe/crash", response_model=ApiResponse[dict[str, str]])
    async def probe_crash() -> ApiResponse[dict[str, str]]:
        """未捕获异常探针：异常原文不得出现在响应中。"""
        raise RuntimeError("内部实现细节：不应出现在响应体中")

    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """返回测试客户端。

    参数:
        app: 待测应用。

    返回:
        Iterator[TestClient]: 关闭异常透传的客户端，以便验证 500 响应契约。
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


async def _ensure_database_exists(database_url: str) -> None:
    """确保测试库存在，避免依赖手工准备环境。

    参数:
        database_url: 测试库连接串。

    异常:
        RuntimeError: 连接串未指定数据库名时抛出。

    注意:
        建库必须用 AUTOCOMMIT：PostgreSQL 不允许在事务块中执行 CREATE DATABASE。
        维护库固定连到 `postgres`，不假设生产库名。
    """
    target = make_url(database_url)
    if target.database is None:
        raise RuntimeError("测试连接串必须包含数据库名。")

    admin_engine = create_async_engine(
        target.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with admin_engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            )
            if exists is None:
                await connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        await admin_engine.dispose()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """返回独立测试库的连接串。

    返回:
        str: 测试库连接串，取自 `JOBARK_TEST_DATABASE_URL`。

    注意:
        本夹具是数据库集成测试的唯一开关：未设置环境变量时跳过，而不是让测试因缺库而失败；
        设置后会自动创建缺失的测试库。测试库与开发库必须分离，避免迁移测试清空开发数据。
    """
    database_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not database_url:
        pytest.skip(f"未设置 {TEST_DATABASE_URL_ENV}，跳过数据库集成测试。")
    asyncio.run(_ensure_database_exists(database_url))
    return database_url


async def _truncate_domain_tables(database_url: str) -> None:
    """清空领域表，保证测试之间互不影响。

    参数:
        database_url: 目标数据库连接串。

    注意:
        使用 TRUNCATE 而不是 DELETE：前者一次完成且重置序列，不会因为外键顺序反复失败。
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE {', '.join(_DOMAIN_TABLES)} CASCADE"))
    finally:
        await engine.dispose()


def _upgrade_schema() -> None:
    """把测试库迁移到最新版本。

    注意:
        每次使用数据库夹具时都执行一次：迁移是幂等的，而已迁移的库执行 upgrade 是空操作。
        刻意不做"缺表才升级"的判断——那种判断会在新增迁移时静默失效，表现为测试里缺表，
        让人误以为是代码问题。
        通过 Alembic 迁移建表，而不是 `create_all`：测试必须验证的是真实迁移产物，
        两者不一致时应当由测试暴露，而不是被"测试里另建一套表"掩盖。
        必须用 `alembic.command`（同步）执行：异步 `env.py` 内部调用 `asyncio.run`，
        在已运行的事件循环里会直接报错。
    """
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")


@pytest.fixture
def db_client(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """返回指向测试库、且数据已清空的客户端。

    参数:
        test_database_url: 会话级测试库连接串。
        monkeypatch: 用于把连接串注入应用配置。

    返回:
        Iterator[TestClient]: 可在真实数据库上验证领域接口的客户端。
    """
    monkeypatch.setenv("JOBARK_DATABASE_URL", test_database_url)
    # 配置单例带缓存，必须清除，否则应用会继续连接开发库。
    get_settings.cache_clear()

    _upgrade_schema()
    asyncio.run(_truncate_domain_tables(test_database_url))

    application = create_app(
        Settings(
            app_env=AppEnv.TEST,
            log_level="WARNING",
            database_url=test_database_url,
            # 与 conftest 其他夹具一致：运行期禁用 .env 读取。
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        yield client
    get_settings.cache_clear()
