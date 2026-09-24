"""默认模型切换的并发与冲突映射回归测试。

这些用例直接使用隔离 PostgreSQL，验证三件事：

1. 两个请求互相把对方设为默认时**不会死锁**，且最终始终只有一个默认模型；
2. 数据库唯一冲突（部分唯一索引）被映射为可理解的 409，而不是 500；
3. 死锁与序列化失败映射为 409，而**非冲突类**数据库错误（例如连接失败）不会被伪装成 409。

刻意使用真实数据库而不是替身：默认模型的"至多一个"由部分唯一索引保证，
只有真实约束才能证明服务层的加锁顺序与错误映射确实有效。
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai import repository as repo
from app.ai import service
from app.ai.models import AiModel, AiProvider
from app.core.errors import ConflictError


class _DeadlockError(Exception):
    """模拟 asyncpg 的死锁异常：只提供映射所需的 `sqlstate`。"""

    sqlstate = "40P01"


class _ConnectionError(Exception):
    """模拟非冲突类数据库故障：没有 SQLSTATE，必须保持原样上抛。"""


def _deadlock() -> OperationalError:
    """构造带死锁状态码的 SQLAlchemy `OperationalError`。"""
    return OperationalError("SELECT ... FOR UPDATE", {}, _DeadlockError("deadlock detected"))


def _connection_failure() -> OperationalError:
    """构造没有 SQLSTATE 的连接失败错误。"""
    return OperationalError("SELECT 1", {}, _ConnectionError("connection refused"))


async def _seed(
    factory: async_sessionmaker[AsyncSession], names: list[str], *, default_index: int | None = 0
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """写入一个服务商与若干模型，并把指定下标的模型标记为默认。

    参数:
        factory: 测试库会话工厂。
        names: 模型名称列表；同时用作远端模型标识。
        default_index: 默认模型下标；传 None 表示不设置默认模型。

    返回:
        tuple[uuid.UUID, list[uuid.UUID]]: 服务商主键与按输入顺序排列的模型主键。
    """
    async with factory() as session:
        provider = AiProvider(
            name=f"并发服务-{uuid.uuid4().hex[:8]}", base_url="https://example.test/v1", is_enabled=True
        )
        session.add(provider)
        await session.flush()
        models = [
            AiModel(
                provider_id=provider.id,
                name=name,
                remote_model_id=name,
                is_default=index == default_index,
            )
            for index, name in enumerate(names)
        ]
        session.add_all(models)
        await session.commit()
        return provider.id, [model.id for model in models]


async def _default_ids(factory: async_sessionmaker[AsyncSession]) -> list[uuid.UUID]:
    """读取当前所有默认模型主键。"""
    async with factory() as session:
        rows = (await session.scalars(select(AiModel))).all()
    return [row.id for row in rows if row.is_default]


async def test_concurrent_mutual_switch_keeps_single_default(db_client: TestClient, test_database_url: str) -> None:
    """两个请求互相切换默认模型时既不死锁，也不会留下两个默认模型。

    为什么需要这条断言：加锁顺序若为"先目标、后当前默认"，A→B 与 B→A 会各持一行互相等待，
    形成死锁环。死锁在 PostgreSQL 中会被检测并中止其中一个事务，表现为用户可见的随机失败。
    """
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        _, ids = await _seed(factory, ["m1", "m2"])
        barrier = asyncio.Barrier(2)

        async def switch(model_id: uuid.UUID) -> None:
            """在屏障处与另一个请求对齐后切换默认模型。"""
            async with factory() as session:
                async with barrier:
                    pass
                await service.set_default_model(session, model_id)

        await asyncio.gather(switch(ids[1]), switch(ids[0]))

        defaults = await _default_ids(factory)
        assert len(defaults) == 1
        assert defaults[0] in set(ids)
    finally:
        await engine.dispose()


async def test_concurrent_set_without_existing_default_never_produces_two_defaults(
    db_client: TestClient, test_database_url: str
) -> None:
    """没有默认模型时并发设置：要么成功，要么得到 409，绝不出现两个默认模型或 500 类错误。

    这条用例是"唯一冲突必须映射为 409"的最强证据：两个请求都看不到旧默认，都会尝试写入
    `is_default = true`，由部分唯一索引拒绝其一。修复前该路径会把 `IntegrityError` 直接抛出
    （对外表现为 500），修复后必须变成可理解的 409。
    """
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        _, ids = await _seed(factory, ["m1", "m2"], default_index=None)
        barrier = asyncio.Barrier(2)
        conflicts: list[str] = []

        async def switch(model_id: uuid.UUID) -> None:
            """并发设置默认；唯一约束拒绝时记录为可理解的冲突。"""
            async with factory() as session:
                async with barrier:
                    pass
                try:
                    await service.set_default_model(session, model_id)
                except ConflictError as error:
                    conflicts.append(error.message)

        await asyncio.gather(switch(ids[0]), switch(ids[1]))

        defaults = await _default_ids(factory)
        assert len(defaults) == 1
        assert defaults[0] in set(ids)
        # 允许其中一个请求被拒绝，但拒绝理由必须是面向用户的安全文案。
        assert all("冲突" in message or "默认" in message for message in conflicts)
    finally:
        await engine.dispose()


async def test_unique_conflict_maps_to_conflict(
    db_client: TestClient, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """部分唯一索引冲突必须映射为 409，并回滚为原默认模型。

    这里刻意隐藏"当前默认行"来模拟竞态窗口：服务层看不到旧默认，于是尝试直接设置新默认，
    由数据库唯一索引兜住。断言的重点不是冲突发生，而是**冲突被安全地表达为 409**，
    且事务回滚后不会出现两个默认模型。
    """
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        _, ids = await _seed(factory, ["m1", "m2"])
        original = repo.lock_default_candidates

        async def hide_current(session: AsyncSession, model_id: uuid.UUID) -> list[AiModel]:
            """只返回目标行，模拟"看不到当前默认"的并发窗口。"""
            rows = await original(session, model_id)
            return [row for row in rows if row.id == model_id]

        monkeypatch.setattr(service.repo, "lock_default_candidates", hide_current)

        async with factory() as session:
            with pytest.raises(ConflictError):
                await service.set_default_model(session, ids[1])

        assert await _default_ids(factory) == [ids[0]]
    finally:
        await engine.dispose()


async def test_deadlock_maps_to_conflict(
    db_client: TestClient, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """死锁必须映射为可理解的 409，而不是把数据库错误变成 500。"""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        _, ids = await _seed(factory, ["m1", "m2"])

        async def deadlock(session: AsyncSession, model_id: uuid.UUID) -> list[AiModel]:
            """模拟 PostgreSQL 检测到死锁后中止本事务。"""
            raise _deadlock()

        monkeypatch.setattr(service.repo, "lock_default_candidates", deadlock)

        async with factory() as session:
            with pytest.raises(ConflictError):
                await service.set_default_model(session, ids[1])
    finally:
        await engine.dispose()


async def test_non_conflict_database_error_is_not_masked(
    db_client: TestClient, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """连接失败等非冲突错误必须原样上抛，不能被伪装成 409。

    否则"数据库连不上"会被报告为"配置冲突"，把可诊断的故障藏起来。
    """
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        _, ids = await _seed(factory, ["m1", "m2"])

        async def broken(session: AsyncSession, model_id: uuid.UUID) -> list[AiModel]:
            """模拟没有 SQLSTATE 的数据库故障。"""
            raise _connection_failure()

        monkeypatch.setattr(service.repo, "lock_default_candidates", broken)

        async with factory() as session:
            with pytest.raises(OperationalError):
                await service.set_default_model(session, ids[1])
    finally:
        await engine.dispose()
