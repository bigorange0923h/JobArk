"""数据库引擎、会话与模型基类。

数据访问统一使用异步 SQLAlchemy（`AsyncSession` + asyncpg）。异步改变的是等待数据库往返期间
是否让出事件循环，不改变数据可见性：每次查询读到的都是该时刻数据库已提交的数据。

两条硬约束（见 ADR 0002）：

1. 会话依赖不做隐式提交。事务边界由应用服务显式控制，避免"请求成功但数据未落库"的静默失败，
   也避免在不确定的重试中重复提交。
2. 调用外部服务（LLM、浏览器、第三方 HTTP）必须在事务之外进行。领域服务的顺序是：
   取数据 → 结束事务 → 等待外部 → 按需开启新事务写回。
"""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import Settings

# 约束命名约定：让 Alembic 生成与回退的脚本中索引、外键、唯一约束名可预测。
# 缺少约定时匿名约束由数据库自动命名，不同环境下名字不一致，降级脚本将无法稳定引用。
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有领域模型的声明式基类。

    领域模块在自己的 `models.py` 中继承本类；Alembic 通过 `Base.metadata` 感知全部表，
    因此新增领域后必须在 `migrations/env.py` 中显式导入其 `models` 模块。
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Database:
    """引擎与会话工厂的持有者。

    实例挂在 `app.state.database` 上，由应用 lifespan 创建与释放；不使用模块级全局引擎，
    以免测试之间互相污染连接池。
    """

    def __init__(self, settings: Settings) -> None:
        """初始化数据库持有者。

        参数:
            settings: 应用配置，提供连接串与 SQL 回显开关。

        注意:
            引擎创建是惰性的，不会立即建立连接，因此数据库暂时不可用时应用仍可启动。
        """
        self._engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=settings.database_echo,
            # 连接可能已被数据库或中间网络设备断开，取用前先探活，避免偶发的陈旧连接错误。
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        """返回底层引擎。

        返回:
            AsyncEngine: 供需要直接执行语句或健康探测的调用方使用。
        """
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        """打开一个独立会话。

        返回:
            AsyncIterator[AsyncSession]: 会话上下文；退出时无论成功与否都会关闭，
            异常时先回滚，避免把失败的部分写入随连接归还连接池。

        注意:
            本方法不提交事务。调用方必须显式 `await session.commit()`，这是刻意设计：
            隐式提交会让"忘记提交"与"提交失败"都变得不可见。
        """
        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        """释放连接池；由应用关闭流程调用。"""
        await self._engine.dispose()


def get_database(request: Request) -> Database:
    """FastAPI 依赖：返回应用级数据库持有者。

    参数:
        request: 当前请求，用于读取应用状态。

    返回:
        Database: 与当前应用实例绑定的数据库持有者。
    """
    database: Database = request.app.state.database
    return database


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：为每个请求提供独立会话。

    参数:
        request: 当前请求。

    返回:
        AsyncIterator[AsyncSession]: 请求级会话，请求结束即关闭。

    注意:
        每个请求独立会话，不复用跨请求事务；因此不存在"上一个请求未提交的事务影响本次查询"
        这类隐蔽问题。
    """
    async with get_database(request).session() as session:
        yield session
