"""为既有同步 API 测试提供开发库事务隔离；不清空或提交业务数据。"""

import uuid
from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, AsyncTransaction, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database import get_session
from app.main import create_app


@contextmanager
def development_db_client() -> Generator[TestClient]:
    """在客户端同一事件循环建立外层事务；每次请求的 commit 只释放保存点。"""
    settings = get_settings()
    application = create_app(settings)
    schema = "jobark_verify_" + uuid.uuid4().hex
    with TestClient(application, raise_server_exceptions=False) as client:
        # Starlette 未提供 portal 的完整类型；运行期 API 已由 TestClient 上下文初始化。
        portal = cast(Any, client).portal
        assert portal is not None
        engine = create_async_engine(settings.database_url, poolclass=NullPool, connect_args={"timeout": 8})
        connection: AsyncConnection = portal.call(engine.connect)
        outer: AsyncTransaction = portal.call(connection.begin)

        async def setup() -> None:
            """迁移只能绑定本次连接，随机 schema 不包含 public 搜索路径。"""
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.execute(text("SET LOCAL statement_timeout='20s'"))
            root = Path(__file__).resolve().parents[1]
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))

            def migrate(sync_connection: Any) -> None:
                """避免 Alembic 环境新建连接写入业务 schema。"""
                config.attributes["connection"] = sync_connection
                command.upgrade(config, "head")

            await connection.run_sync(migrate)

        async def override_session() -> AsyncIterator[AsyncSession]:
            """请求使用保存点，成功提交和失败回滚都不逃逸外层事务。"""
            async with AsyncSession(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            ) as session:
                yield session

        application.dependency_overrides[get_session] = override_session
        try:
            portal.call(setup)
            yield client
        finally:
            portal.call(outer.rollback)
            portal.call(connection.close)
            portal.call(engine.dispose)
