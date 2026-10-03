"""数据库日志隐私回归：仅执行合成 SELECT，不访问或修改业务表。"""

import logging
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import AppEnv, Settings, get_settings
from app.core.database import Database


@pytest_asyncio.fixture
async def echo_database() -> AsyncIterator[Database]:
    """显式允许连接时提供开启 SQL 回显的数据库；测试结束关闭全部连接。"""
    database_url = os.environ.get("JOBARK_TEST_DATABASE_URL")
    if not database_url:
        if os.environ.get("JOBARK_VERIFY_DEVELOPMENT_DATABASE") != "1":
            pytest.skip("未提供专用测试库，也未显式启用只读开发库验证。")
        database_url = get_settings().database_url
    settings = Settings(
        app_env=AppEnv.TEST,
        database_url=database_url,
        database_echo=True,
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    database = Database(settings)
    try:
        yield database
    finally:
        await database.dispose()


async def test_select_echo_retains_statement_and_hides_parameters(
    echo_database: Database, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """正常绑定查询结果保持，回显和日志仅保留 SQL，不能保存合成正文参数。"""
    marker = "synthetic-jobark-candidate-success-secret"
    caplog.set_level(logging.INFO, logger="sqlalchemy.engine.Engine")
    async with echo_database.engine.connect() as connection:
        transaction = await connection.begin()
        try:
            result = await connection.execute(text("SELECT CAST(:value AS text)"), {"value": marker})
            assert result.scalar_one() == marker
        finally:
            await transaction.rollback()
    captured = capsys.readouterr()
    logged = caplog.text + captured.out + captured.err
    assert "SELECT CAST(" in logged
    assert marker not in logged
    assert "SQL parameters hidden" in logged


async def test_database_error_retains_statement_and_hides_parameters(
    echo_database: Database, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """静态除零错误不涉及上游输入回显；异常字符串和日志隐藏绑定参数。"""
    marker = "synthetic-jobark-candidate-failure-secret"
    caplog.set_level(logging.INFO, logger="sqlalchemy.engine.Engine")
    async with echo_database.engine.connect() as connection:
        transaction = await connection.begin()
        try:
            with pytest.raises(DBAPIError) as raised:
                await connection.execute(text("SELECT CAST(:value AS text), 1 / 0"), {"value": marker})
        finally:
            await transaction.rollback()
    error_text = str(raised.value)
    captured = capsys.readouterr()
    logged = caplog.text + captured.out + captured.err
    assert "SELECT CAST(" in error_text
    assert marker not in error_text
    assert "SQL parameters hidden" in error_text
    assert "SELECT CAST(" in logged
    assert marker not in logged
    assert "SQL parameters hidden" in logged
