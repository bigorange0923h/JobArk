"""AI 配置领域的数据访问层。

只负责查询与持久化辅助，不做业务判断：唯一性、默认模型切换、凭据边界与乐观锁规则
都在 `service.py`。事务由服务层控制，本层不调用 `commit`。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import NoReturn

from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.errors import ConflictError

from .models import AiModel, AiProvider

WRITE_CONFLICT_MESSAGE = "配置保存失败：存在重复或并发冲突，请刷新后重试。"
"""数据库写入冲突的默认用户提示；调用方可传入更具体的文案。"""

# 可安全映射为 409 的 PostgreSQL SQLSTATE：
# 23505 唯一约束冲突、40P01 死锁、40001 序列化失败。
# 刻意只列这三个：其他数据库错误（连接失败、权限不足等）必须保持原样上抛。
_CONFLICT_SQLSTATES = frozenset({"23505", "40P01", "40001"})


async def list_providers(session: AsyncSession) -> Sequence[AiProvider]:
    """按创建时间列出全部服务商。

    参数:
        session: 当前会话。

    返回:
        Sequence[AiProvider]: 服务商列表，最早的在前。
    """
    return (await session.scalars(select(AiProvider).order_by(AiProvider.created_at))).all()


async def list_models(session: AsyncSession) -> Sequence[AiModel]:
    """按创建时间列出全部模型。

    参数:
        session: 当前会话。

    返回:
        Sequence[AiModel]: 模型列表，最早的在前。
    """
    return (await session.scalars(select(AiModel).order_by(AiModel.created_at))).all()


async def list_models_for_provider(session: AsyncSession, provider_id: uuid.UUID) -> Sequence[AiModel]:
    """列出某服务商下的模型。

    参数:
        session: 当前会话。
        provider_id: 所属服务商主键。

    返回:
        Sequence[AiModel]: 该服务商的模型列表，最早的在前。
    """
    return (
        await session.scalars(select(AiModel).where(AiModel.provider_id == provider_id).order_by(AiModel.created_at))
    ).all()


async def get_provider(session: AsyncSession, provider_id: uuid.UUID) -> AiProvider | None:
    """按主键读取服务商。

    参数:
        session: 当前会话。
        provider_id: 服务商主键。

    返回:
        AiProvider | None: 服务商实例；不存在时为 None。
    """
    return await session.get(AiProvider, provider_id)


async def get_model(session: AsyncSession, model_id: uuid.UUID) -> AiModel | None:
    """按主键读取模型。

    参数:
        session: 当前会话。
        model_id: 模型主键。

    返回:
        AiModel | None: 模型实例；不存在时为 None。
    """
    return await session.get(AiModel, model_id)


async def get_default_model(session: AsyncSession) -> AiModel | None:
    """读取当前默认模型。

    参数:
        session: 当前会话。

    返回:
        AiModel | None: 默认模型；尚未设置时为 None。

    注意:
        本函数不加锁，仅用于只读判断（例如"是否已有默认模型"）。
        切换默认模型必须使用 `lock_default_candidates`，它一次性锁定目标与当前默认。
    """
    return await session.scalar(select(AiModel).where(AiModel.is_default.is_(True)))


async def has_default_model(session: AsyncSession, provider_id: uuid.UUID) -> bool:
    """判断某服务商下是否存在默认模型。

    参数:
        session: 当前会话。
        provider_id: 服务商主键。

    返回:
        bool: 存在默认模型时返回 True。
    """
    count = await session.scalar(
        select(func.count())
        .select_from(AiModel)
        .where(AiModel.provider_id == provider_id, AiModel.is_default.is_(True))
    )
    return bool(count)


async def provider_name_exists(session: AsyncSession, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
    """判断服务商名称是否已被占用。

    参数:
        session: 当前会话。
        name: 待检查的显示名称。
        exclude_id: 需要排除的记录（更新自身时使用）。

    返回:
        bool: 已存在返回 True。
    """
    statement = select(func.count()).select_from(AiProvider).where(AiProvider.name == name)
    if exclude_id is not None:
        statement = statement.where(AiProvider.id != exclude_id)
    return bool(await session.scalar(statement))


async def model_remote_id_exists(
    session: AsyncSession,
    provider_id: uuid.UUID,
    remote_model_id: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """判断同一服务商下的远端模型标识是否已被占用。

    参数:
        session: 当前会话。
        provider_id: 所属服务商主键。
        remote_model_id: 待检查的远端模型标识。
        exclude_id: 需要排除的记录（更新自身时使用）。

    返回:
        bool: 已存在返回 True。
    """
    statement = (
        select(func.count())
        .select_from(AiModel)
        .where(AiModel.provider_id == provider_id, AiModel.remote_model_id == remote_model_id)
    )
    if exclude_id is not None:
        statement = statement.where(AiModel.id != exclude_id)
    return bool(await session.scalar(statement))


async def map_write_error(session: AsyncSession, error: DBAPIError, message: str) -> NoReturn:
    """把可安全解释的数据库写入错误映射为 409，其余原样上抛。

    参数:
        session: 当前会话；映射前会先回滚，丢弃已失败的事务。
        error: 捕获到的 SQLAlchemy 数据库错误。
        message: 面向用户的安全冲突提示。

    异常:
        ConflictError: `error` 的 SQLSTATE 属于唯一冲突、死锁或序列化失败。
        DBAPIError: 其他数据库错误原样上抛。

    注意:
        刻意不把所有 `DBAPIError` 都当成 409：若"数据库连不上"被报告成"配置冲突"，
        可诊断的故障会被藏起来，用户还会反复重试无效操作。
    """
    if getattr(error.orig, "sqlstate", None) in _CONFLICT_SQLSTATES:
        await session.rollback()
        raise ConflictError(message) from error
    raise error


async def lock_default_candidates(session: AsyncSession, model_id: uuid.UUID) -> Sequence[AiModel]:
    """一次性锁定"目标模型"与"当前默认模型"，供默认模型切换使用。

    参数:
        session: 当前会话。
        model_id: 目标模型主键。

    返回:
        Sequence[AiModel]: 命中的行；至多两行（目标 + 当前默认）。

    注意:
        必须用**单条**语句同时锁定并按主键排序：这样并发切换会以相同顺序获取同一组锁，
        不会形成互相等待的环；拆成"先锁目标、再锁当前默认"会让两个请求各自持有一行再互相
        等待，把加锁结果交给调度时序，属于不可控行为。
    """
    statement = (
        select(AiModel)
        .where(or_(AiModel.id == model_id, AiModel.is_default.is_(True)))
        .order_by(AiModel.id)
        .with_for_update()
    )
    return (await session.scalars(statement)).all()


async def add[ModelT: Base](session: AsyncSession, entity: ModelT) -> ModelT:
    """加入实体并 flush，把约束冲突映射为安全冲突错误。

    参数:
        session: 当前会话。
        entity: 待新增实体。

    返回:
        ModelT: 已 flush 的实体。

    异常:
        ConflictError: 唯一约束冲突（名称或远端模型标识重复、并发设置默认模型）。

    注意:
        服务层已提前做可解释的重复检查；这里的兜底用于并发与部分唯一索引，
        避免把 PostgreSQL 原始错误直接变成 500。
    """
    session.add(entity)
    try:
        await session.flush()
    except DBAPIError as error:
        await map_write_error(session, error, WRITE_CONFLICT_MESSAGE)
    return entity


async def remove(session: AsyncSession, entity: Base) -> None:
    """删除实体并 flush。

    参数:
        session: 当前会话。
        entity: 待删除实体。

    注意:
        只 flush 不 commit：提交由服务层决定。服务商删除后其模型由数据库外键级联清理。
    """
    await session.delete(entity)
    await session.flush()
