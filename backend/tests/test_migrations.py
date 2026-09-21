"""迁移链路的集成验证。

阶段 0 的验收标准是"空数据库可重复迁移"，因此这些测试对真实 PostgreSQL 反复执行
`upgrade`/`downgrade`，而不是只断言迁移脚本存在。未配置测试库时整组测试被跳过。

注意:
    这些测试必须是同步的。Alembic 的异步 `env.py` 内部调用 `asyncio.run`，
    若在已运行的事件循环中调用会直接报错。
"""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HEAD = "0002"


async def _read_current_revision(database_url: str) -> str | None:
    """读取数据库当前的迁移版本。

    参数:
        database_url: 目标数据库连接串。

    返回:
        str | None: 当前版本号；尚未执行过任何迁移（版本表不存在）时为 None。

    注意:
        引擎在同一事件循环内创建与释放：跨 `asyncio.run` 释放会让 asyncpg 连接归属错误的循环。
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            try:
                result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            except ProgrammingError:
                # 版本表不存在，等价于停留在基线之前。
                return None
            return result.scalar_one_or_none()
    finally:
        await engine.dispose()


def _current_revision(database_url: str) -> str | None:
    """同步读取当前迁移版本，供同步测试使用。

    参数:
        database_url: 目标数据库连接串。

    返回:
        str | None: 当前版本号。
    """
    return asyncio.run(_read_current_revision(database_url))


@pytest.fixture
def alembic_config(test_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    """把迁移环境指向测试库，并保证前后都处于空库状态。

    参数:
        test_database_url: 会话级测试库连接串。
        monkeypatch: 用于临时设置连接串环境变量。

    返回:
        Iterator[Config]: 指向 `backend/alembic.ini` 的配置。

    注意:
        `get_settings` 带缓存，设置环境变量后必须清除，否则迁移会继续连到开发库。
    """
    monkeypatch.setenv("JOBARK_DATABASE_URL", test_database_url)
    get_settings.cache_clear()

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))

    command.downgrade(config, "base")
    try:
        yield config
    finally:
        command.downgrade(config, "base")
        get_settings.cache_clear()


def test_upgrade_from_empty_database_reaches_head(alembic_config: Config, test_database_url: str) -> None:
    """空库执行 upgrade 应到达最新版本。"""
    command.upgrade(alembic_config, "head")

    assert _current_revision(test_database_url) == EXPECTED_HEAD


def test_upgrade_is_idempotent(alembic_config: Config, test_database_url: str) -> None:
    """重复执行 upgrade 不应失败或改变版本。"""
    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")

    assert _current_revision(test_database_url) == EXPECTED_HEAD


def test_downgrade_returns_to_empty_database(alembic_config: Config, test_database_url: str) -> None:
    """downgrade 到基线应移除版本记录，使数据库回到未迁移状态。"""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    assert _current_revision(test_database_url) is None


def test_upgrade_downgrade_upgrade_cycle_is_repeatable(alembic_config: Config, test_database_url: str) -> None:
    """完整的升降级循环应可反复执行，验证迁移链路而非单次结果。"""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    assert _current_revision(test_database_url) == EXPECTED_HEAD
