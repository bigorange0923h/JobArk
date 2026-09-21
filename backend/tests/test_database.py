"""数据库持有者与请求级会话的集成验证。

未配置 `JOBARK_TEST_DATABASE_URL` 时这些测试会被跳过。
"""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppEnv, Settings
from app.core.database import Database, get_session
from app.core.responses import ApiResponse, success
from app.main import create_app


def _test_settings(database_url: str) -> Settings:
    """构造指向测试库的配置。

    参数:
        database_url: 测试库连接串。

    返回:
        Settings: 不读取 `.env` 的测试配置。
    """
    return Settings(
        app_env=AppEnv.TEST,
        log_level="WARNING",
        database_url=database_url,
        # 与 conftest 一致：运行期禁用 .env 读取，该参数未在生成签名中声明。
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


async def test_session_reaches_configured_database(test_database_url: str) -> None:
    """会话应能在配置的数据库上执行真实查询。"""
    expected_database = make_url(test_database_url).database
    database = Database(_test_settings(test_database_url))
    try:
        async with database.session() as session:
            result = await session.execute(text("SELECT current_database()"))

            assert result.scalar_one() == expected_database
    finally:
        await database.dispose()


def test_session_dependency_is_wired_through_lifespan(test_database_url: str) -> None:
    """请求级会话应由 lifespan 创建的持有者提供，并指向配置的数据库。"""
    expected_database = make_url(test_database_url).database
    application = create_app(_test_settings(test_database_url))

    @application.get("/_probe/db", response_model=ApiResponse[dict[str, str]])
    async def probe_db(session: AsyncSession = Depends(get_session)) -> ApiResponse[dict[str, str]]:
        """数据库探针：返回当前连接所属的数据库名。"""
        result = await session.execute(text("SELECT current_database()"))
        return success({"database": str(result.scalar_one())})

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/_probe/db")

    assert response.status_code == 200
    assert response.json()["data"]["database"] == expected_database


def test_app_starts_without_database_connection(test_database_url: str) -> None:
    """数据库不可用不应阻止应用启动：引擎是惰性的，`/health` 仍须可用。

    这里用不可达端口模拟数据库宕机，验证启动与健康检查不依赖真实连接。
    """
    unreachable = make_url(test_database_url).set(port=1).render_as_string(hide_password=False)
    application: FastAPI = create_app(_test_settings(unreachable))

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ok"}
