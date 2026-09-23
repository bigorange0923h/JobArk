"""AI 配置领域的数据访问层。

只负责查询与持久化辅助，不做业务判断：唯一性、默认模型切换、凭据边界与乐观锁规则
都在 `service.py`。事务由服务层控制，本层不调用 `commit`。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.errors import ConflictError

from .models import AiModel, AiProvider


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


async def get_model_for_update(session: AsyncSession, model_id: uuid.UUID) -> AiModel | None:
    """按主键读取模型并加行锁。

    参数:
        session: 当前会话。
        model_id: 模型主键。

    返回:
        AiModel | None: 已加锁的模型实例；不存在时为 None。

    注意:
        切换默认模型必须锁定目标行，防止并发切换同时通过应用层检查。
    """
    return await session.scalar(select(AiModel).where(AiModel.id == model_id).with_for_update())


async def get_default_model(session: AsyncSession, *, for_update: bool = False) -> AiModel | None:
    """读取当前默认模型。

    参数:
        session: 当前会话。
        for_update: 是否加行锁；切换默认时需与目标行一起锁定，形成确定的加锁顺序。

    返回:
        AiModel | None: 默认模型；尚未设置时为 None。
    """
    statement = select(AiModel).where(AiModel.is_default.is_(True))
    if for_update:
        statement = statement.with_for_update()
    return await session.scalar(statement)


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
    except IntegrityError as error:
        await session.rollback()
        raise ConflictError("配置保存失败：存在重复或并发冲突，请刷新后重试。") from error
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
