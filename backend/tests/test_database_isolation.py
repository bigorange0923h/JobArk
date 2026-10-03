"""共用开发数据库时验证真实连接的 schema 隔离，不读取业务正文。"""

import asyncio
from typing import Annotated, cast

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from tests.database_sandbox import shared_database_schema

from app.core.config import get_settings
from app.core.database import Database, get_database
from app.core.responses import ApiResponse, success


def test_shared_database_url_uses_only_random_schema(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """应用和测试地址完全相同时仍可运行，连接只解析本次随机 schema。"""
    monkeypatch.setenv("JOBARK_TEST_DATABASE_URL", get_settings().database_url)
    database_url: str = request.getfixturevalue("test_database_url")

    async def read_search_path() -> None:
        """独立连接验证启动参数，不把 public 当作测试数据的回退来源。"""
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                schema = await connection.scalar(text("SELECT current_schema()"))
                assert isinstance(schema, str) and schema.startswith("jobark_test_")
                assert await connection.scalar(text("SELECT current_schemas(false)")) == [schema]
        finally:
            await engine.dispose()

    asyncio.run(read_search_path())


def test_database_holder_uses_same_transaction_as_api(db_client: TestClient) -> None:
    """流式入口直接打开持有者会话时也必须留在 API 的随机 schema 内。"""
    application = cast(FastAPI, db_client.app)

    @application.get("/_probe/database-holder", response_model=ApiResponse[dict[str, str]])
    async def probe(database: Annotated[Database, Depends(get_database)]) -> ApiResponse[dict[str, str]]:
        """只读取当前 schema，防止会话持有者绕过请求级依赖的隔离。"""
        async with database.session() as session:
            schema = await session.scalar(text("SELECT current_schema()"))
            return success({"schema": str(schema)})

    response = db_client.get("/_probe/database-holder")
    assert response.status_code == 200
    assert response.json()["data"]["schema"].startswith("jobark_verify_")


async def _commit_and_read_from_another_connection(database_url: str) -> None:
    """提交合成记录后由另一独立连接读取，覆盖并发用例需要的可见性。"""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE isolation_probe (value integer NOT NULL)"))
            await connection.execute(text("INSERT INTO isolation_probe VALUES (17)"))
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT value FROM isolation_probe")) == 17
    finally:
        await engine.dispose()


async def _schema_exists(database_url: str, schema: str) -> bool:
    """只查目录验证清理结果，不访问业务正文。"""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return bool(
                await connection.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"), {"schema": schema}
                )
            )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("fail", [False, True], ids=["success", "test-error"])
def test_schema_cleanup_includes_committed_data_and_test_errors(fail: bool) -> None:
    """正常和异常退出均移除本次 schema，包括已提交的合成记录。"""
    database_url = get_settings().database_url
    schema = ""

    def exercise() -> None:
        """在同库临时范围模拟有提交的测试，错误不能绕过清理。"""
        nonlocal schema
        with shared_database_schema(database_url) as sandbox:
            schema = sandbox.schema
            asyncio.run(_commit_and_read_from_another_connection(sandbox.database_url))
            if fail:
                raise RuntimeError("synthetic test failure")

    if fail:
        with pytest.raises(RuntimeError, match="synthetic test failure"):
            exercise()
    else:
        exercise()
    assert schema
    assert not asyncio.run(_schema_exists(database_url, schema))
