"""测试夹具。

每个测试通过 `create_app` 构建独立应用实例，并挂载仅用于验证契约的探针路由。
探针路由不进入生产入口，避免为测试而在正式应用上暴露调试接口。

测试配置显式禁用 `.env` 加载，防止开发者本地配置让测试结果不可复现。
数据库测试默认共用应用数据库。普通 API 用例在随机 schema 和外层事务中回滚；
多连接及独立迁移用例仅清理各自创建的随机 schema，不创建数据库或清空业务表。
旧 `JOBARK_TEST_DATABASE_URL` 只是可选地址覆盖，与应用地址相同允许。
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.database_sandbox import shared_database_schema
from tests.development_database import development_db_client

from app.core.config import AppEnv, Settings, get_settings
from app.core.errors import ResourceNotFoundError
from app.core.responses import ApiResponse, success
from app.main import create_app

TEST_DATABASE_URL_ENV = "JOBARK_TEST_DATABASE_URL"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _disable_forced_mock_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试默认关闭"local 环境强制 mock 抽取"的临时开关。

    参数:
        monkeypatch: 用于把模块常量临时置空的夹具。

    注意:
        领域服务读取的是全局 `get_settings()`，它会加载开发者本地的 `backend/.env`；本机 `.env`
        的 `JOBARK_APP_ENV=local` 会让导入流程默认返回 mock 数据，使大量用例悄悄测不到真实分支。
        这里统一关掉，需要 mock 的用例自行开启（设 `profile_import_fixture` 或临时打开该常量）。
    """
    monkeypatch.setattr("app.modules.profile.import_service._FORCE_MOCK_EXTRACTION_IN", None)


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


@pytest.fixture
def test_database_url() -> Iterator[str]:
    """在应用数据库中给多连接用例创建随机 schema，退出只清理本次范围。"""
    database_url = os.environ.get(TEST_DATABASE_URL_ENV) or get_settings().database_url
    try:
        with shared_database_schema(database_url) as sandbox:
            yield sandbox.database_url
    finally:
        get_settings.cache_clear()


def _upgrade_schema() -> None:
    """把测试库迁移到最新版本。

    注意:
        仅供多连接夹具在本次新建随机 schema 中运行；不升级业务 schema。
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
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """默认共用开发库，以事务或随机 schema 隔离客户端。

    参数:
        request: 识别本用例是否另需独立数据库连接。
        monkeypatch: 多连接用例把隔离地址注入应用配置。

    返回:
        Iterator[TestClient]: 可在真实数据库上验证领域接口的客户端。
    """
    if "test_database_url" not in request.fixturenames:
        database_url = os.environ.get(TEST_DATABASE_URL_ENV) or get_settings().database_url
        try:
            with development_db_client(database_url) as client:
                yield client
        finally:
            get_settings.cache_clear()
        return
    test_database_url: str = request.getfixturevalue("test_database_url")
    monkeypatch.setenv("JOBARK_DATABASE_URL", test_database_url)
    # 配置单例带缓存，必须清除，否则应用会继续连接开发库。
    get_settings.cache_clear()

    try:
        _upgrade_schema()
        application = create_app(
            Settings(
                app_env=AppEnv.TEST,
                log_level="WARNING",
                database_url=test_database_url,
                _env_file=None,  # pyright: ignore[reportCallIssue]
            )
        )
        with TestClient(application, raise_server_exceptions=False) as client:
            yield client
    finally:
        get_settings.cache_clear()
