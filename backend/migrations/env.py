"""Alembic 迁移环境。

连接串从应用配置读取（`JOBARK_DATABASE_URL`），不在 `alembic.ini` 中保存凭据。
迁移通过异步引擎执行，与应用的数据访问范式保持一致（见 ADR 0002）。

**领域模型必须在此显式导入**：autogenerate 只能感知已加载进 `Base.metadata` 的表，
漏导入的表现是"生成的迁移里缺少某张表"，属于静默错误，因此采用显式登记而非自动扫描。
"""

import asyncio
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.ai import models as ai_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.core.config import get_settings
from app.core.database import Base
from app.modules.application import models as application_models  # noqa: F401  # pyright: ignore[reportUnusedImport]

# 领域模型的显式导入登记处。autogenerate 只能感知已加载进 Base.metadata 的表，
# 漏导入的表现是"生成的迁移里缺少某张表"，属于静默错误，因此这里不做自动扫描。
from app.modules.job import models as job_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.modules.matching import models as matching_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.modules.profile import models as profile_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.modules.resume import models as resume_models  # noqa: F401  # pyright: ignore[reportUnusedImport]

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    """返回迁移使用的连接串。

    返回:
        str: 应用配置中的异步连接串；测试通过环境变量指向独立测试库。
    """
    return get_settings().database_url


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连接数据库。

    注意:
        离线模式无法读取数据库当前状态，因此仅用于人工审阅生成的语句，
        真实迁移必须走在线模式。
    """
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    """在已建立的连接上执行迁移。

    参数:
        connection: 由异步连接经 `run_sync` 提供的同步外观连接。
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # 类型与默认值变更也要进入 autogenerate 结果，否则模型与数据库会悄悄漂移。
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    """使用异步引擎执行迁移。"""
    configuration: dict[str, Any] = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        # 迁移是一次性任务，不需要连接池；NullPool 避免迁移结束后残留连接。
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式：连接数据库并执行迁移。"""
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
