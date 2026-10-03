"""在同一数据库中提供多连接可见的随机 schema，不创建或清空数据库。"""

import asyncio
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlencode

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


@dataclass(frozen=True)
class DatabaseSandbox:
    """本次隔离范围；URL 保持同一数据库，仅给所有连接固定随机 schema。"""

    database_url: str
    schema: str


async def _change_schema(database_url: str, schema: str, *, create: bool) -> None:
    """仅创建或删除调用方刚生成的随机 schema；连接始终在本事件循环关闭。"""
    engine = create_async_engine(database_url, hide_parameters=True, poolclass=NullPool, connect_args={"timeout": 8})
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL statement_timeout = '20s'"))
            await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            # schema 只能来自本模块的 UUID，不接受配置或外部输入作为删除目标。
            statement = f'CREATE SCHEMA "{schema}"' if create else f'DROP SCHEMA "{schema}" CASCADE'
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@contextmanager
def shared_database_schema(database_url: str) -> Generator[DatabaseSandbox]:
    """创建同库隔离范围，正常结束或测试异常都只删除本次 schema。

    参数:
        database_url: 应用的 asyncpg 连接地址，也允许使用原测试地址覆盖。
    返回:
        DatabaseSandbox: 多个独立连接可共享的隔离地址和随机 schema 名。
    副作用:
        临时提交该 schema 的 DDL，退出删除它；不修改业务 schema。
    """
    schema = "jobark_test_" + uuid.uuid4().hex
    # asyncpg 的 DSN 支持启动时设置 search_path，关键字连接参数仍取外层 URL；
    # 内层 DSN 不重复凭据，也不加入 public，迁移降到 base 后不能回读业务表。
    parameters = urlencode({"search_path": schema, "statement_timeout": "20000", "lock_timeout": "5000"})
    isolated_url = (
        make_url(database_url)
        .update_query_dict({"dsn": "postgresql:///?" + parameters})
        .render_as_string(hide_password=False)
    )
    asyncio.run(_change_schema(database_url, schema, create=True))
    try:
        yield DatabaseSandbox(isolated_url, schema)
    finally:
        asyncio.run(_change_schema(database_url, schema, create=False))
