"""AI 模型配置的应用服务。

职责边界：

- 生命周期：服务商与模型的创建、局部更新、启停、删除，以及默认模型切换。
- 默认模型不变量：首个启用模型自动成为默认；同一时刻至多一个默认模型，切换在单个
  事务内完成；默认模型不能被直接停用或删除，其所属服务商也不能被停用或删除。
- 凭据边界：API Key 只以密文入库，读取 DTO 只暴露"是否已配置"与固定掩码；
  连接测试在结束读事务后再发起外部请求，且只发送最小协议请求，不携带任何业务数据。
- 一致性：不追溯改写任何业务事实；模型配置变更只是配置记录。

所有外部 HTTP 都委托给 `app.ai.llm.gateway`，本模块不直接构造请求。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import repository as repo
from app.ai.credentials import CredentialCipher, mask_secret
from app.ai.llm import gateway
from app.ai.models import AiModel, AiProvider
from app.ai.schemas.config import (
    ConnectionTestRead,
    DeleteConfirm,
    ModelCreate,
    ModelRead,
    ModelUpdate,
    ProviderCreate,
    ProviderRead,
    ProviderUpdate,
)
from app.core.config import Settings, get_settings
from app.core.errors import ConflictError, ResourceNotFoundError, ValidationFailedError
from app.core.responses import ErrorDetail
from app.core.versioning import apply_versioned_update

_PROVIDER_NAME_TAKEN = "服务商名称已存在，请更换后重试。"
_REMOTE_ID_TAKEN = "该服务商下已存在相同的远端模型标识。"


def _cipher() -> CredentialCipher:
    """构造凭据加密器；非 LOCAL 环境缺少根密钥时在此安全失败。

    返回:
        CredentialCipher: 由当前运行配置解析出的加密器。

    异常:
        ConflictError: 根密钥缺失或非法（`CredentialCipher.from_settings` 抛出）。
    """
    return CredentialCipher.from_settings(get_settings())


def _apply_api_key(provider: AiProvider, api_key: str | None) -> None:
    """写入或保留服务商凭据。

    参数:
        provider: 目标服务商。
        api_key: 提交的明文 Key；`None` 或空字符串表示**保持已有密文不变**。

    注意:
        空值语义刻意设计为"不变"而不是"清空"，避免前端把未填写的输入框提交为 `""`
        时意外删除凭据。凭据移除只能通过删除服务商完成。
    """
    if api_key:
        provider.api_key_ciphertext = _cipher().encrypt(api_key)
        provider.api_key_mask = mask_secret(api_key)


def _provider_read(provider: AiProvider, models: list[AiModel]) -> ProviderRead:
    """把服务商与其模型组装为读取 DTO。

    参数:
        provider: 服务商实例。
        models: 该服务商下的模型实例列表。

    返回:
        ProviderRead: 只含可展示字段的 DTO，不含任何凭据内容。
    """
    return ProviderRead(
        id=provider.id,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
        version=provider.version,
        name=provider.name,
        base_url=provider.base_url,
        api_key_configured=provider.api_key_ciphertext is not None,
        api_key_mask=provider.api_key_mask,
        description=provider.description,
        is_enabled=provider.is_enabled,
        has_default_model=any(model.is_default for model in models),
        models=[ModelRead.model_validate(model) for model in models],
    )


async def _provider_read_one(session: AsyncSession, provider: AiProvider) -> ProviderRead:
    """读取单个服务商及其模型，组装为读取 DTO。"""
    models = await repo.list_models_for_provider(session, provider.id)
    return _provider_read(provider, list(models))


async def list_providers(session: AsyncSession) -> list[ProviderRead]:
    """列出全部服务商及其模型，供工作台读取。

    参数:
        session: 当前会话。

    返回:
        list[ProviderRead]: 服务商配置列表；空列表表示尚未配置任何服务商。
    """
    providers = await repo.list_providers(session)
    models = await repo.list_models(session)
    grouped: dict[uuid.UUID, list[AiModel]] = {}
    for model in models:
        grouped.setdefault(model.provider_id, []).append(model)
    return [_provider_read(provider, grouped.get(provider.id, [])) for provider in providers]


async def create_provider(session: AsyncSession, payload: ProviderCreate) -> ProviderRead:
    """创建服务商。

    参数:
        session: 当前会话。
        payload: 服务商配置与可选 API Key。

    返回:
        ProviderRead: 新建服务商；其模型列表为空。

    异常:
        ConflictError: 名称重复，或非 LOCAL 环境缺少凭据加密根密钥。
        ValidationFailedError: 接口地址不安全。
    """
    base_url = gateway.validate_base_url(payload.base_url)
    if await repo.provider_name_exists(session, payload.name):
        raise ConflictError(_PROVIDER_NAME_TAKEN, details=[ErrorDetail(field="name", reason="名称已被占用。")])
    provider = AiProvider(name=payload.name, base_url=base_url, description=payload.description, is_enabled=True)
    _apply_api_key(provider, payload.api_key)
    await repo.add(session, provider)
    await session.commit()
    await session.refresh(provider)
    return _provider_read(provider, [])


async def update_provider(session: AsyncSession, provider_id: uuid.UUID, payload: ProviderUpdate) -> ProviderRead:
    """局部更新服务商；未提交字段保持原值。

    参数:
        session: 当前会话。
        provider_id: 服务商主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ProviderRead: 更新后的服务商。

    异常:
        ResourceNotFoundError: 服务商不存在。
        ConflictError: 名称重复、版本过期，或在存在默认模型时停用服务商。
        ValidationFailedError: 接口地址不安全或必填字段被提交为 null。
    """
    provider = await repo.get_provider(session, provider_id)
    if provider is None:
        raise ResourceNotFoundError("AI 服务商不存在。")

    provided = payload.model_fields_set
    updates: dict[str, Any] = {}
    if "name" in provided:
        if payload.name is None:
            raise ValidationFailedError(
                "服务商名称不能为空。", details=[ErrorDetail(field="name", reason="不能为空。")]
            )
        if await repo.provider_name_exists(session, payload.name, exclude_id=provider.id):
            raise ConflictError(_PROVIDER_NAME_TAKEN, details=[ErrorDetail(field="name", reason="名称已被占用。")])
        updates["name"] = payload.name
    if "base_url" in provided:
        if payload.base_url is None:
            raise ValidationFailedError(
                "接口地址不能为空。", details=[ErrorDetail(field="base_url", reason="不能为空。")]
            )
        updates["base_url"] = gateway.validate_base_url(payload.base_url)
    if "description" in provided:
        updates["description"] = payload.description
    if "is_enabled" in provided and payload.is_enabled is not None:
        if not payload.is_enabled and await repo.has_default_model(session, provider.id):
            raise ConflictError("该服务商下存在默认模型，请先设置其他启用模型为默认，再停用服务商。")
        updates["is_enabled"] = payload.is_enabled
    if "api_key" in provided and payload.api_key:
        # 只有提交了非空 Key 才替换；空值在 `_apply_api_key` 的语义中表示保留。
        updates["api_key_ciphertext"] = _cipher().encrypt(payload.api_key)
        updates["api_key_mask"] = mask_secret(payload.api_key)

    if updates:
        try:
            await apply_versioned_update(session, provider, payload.version, updates)
        except IntegrityError as error:
            await session.rollback()
            raise ConflictError(_PROVIDER_NAME_TAKEN) from error
        await session.commit()
    elif provider.version != payload.version:
        raise ConflictError(
            "记录已被更新，请刷新后重试。",
            details=[
                ErrorDetail(field="version", reason=f"当前版本为 {provider.version}，提交的是 {payload.version}。")
            ],
        )
    await session.refresh(provider)
    return await _provider_read_one(session, provider)


async def delete_provider(session: AsyncSession, provider_id: uuid.UUID, payload: DeleteConfirm) -> None:
    """删除服务商及其全部模型。

    参数:
        session: 当前会话。
        provider_id: 服务商主键。
        payload: 删除确认。

    异常:
        ValidationFailedError: 未确认删除。
        ResourceNotFoundError: 服务商不存在。
        ConflictError: 其下仍有默认模型，必须先改默认。

    注意:
        不通过级联删除绕过默认模型约束：数据库外键的 `CASCADE` 只用于保证引用完整，
        服务层必须先显式解除默认模型，用户才知道自己正在失去什么。
    """
    if not payload.confirmed:
        raise ValidationFailedError("请确认删除服务商；删除后其 API Key 不可恢复。")
    provider = await repo.get_provider(session, provider_id)
    if provider is None:
        raise ResourceNotFoundError("AI 服务商不存在。")
    if await repo.has_default_model(session, provider.id):
        raise ConflictError("该服务商下存在默认模型，请先设置其他启用模型为默认，再删除服务商。")
    await repo.remove(session, provider)
    await session.commit()


async def create_model(session: AsyncSession, provider_id: uuid.UUID, payload: ModelCreate) -> ModelRead:
    """在服务商下创建模型。

    参数:
        session: 当前会话。
        provider_id: 所属服务商主键。
        payload: 模型配置。

    返回:
        ModelRead: 新建模型。

    异常:
        ResourceNotFoundError: 服务商不存在。
        ConflictError: 同一服务商下远端模型标识重复。

    注意:
        首个启用模型自动成为默认；仍有并发写入产生两个默认模型的可能，
        因此数据库部分唯一索引是最终保证，冲突会被 `repo.add` 映射为 409。
    """
    provider = await repo.get_provider(session, provider_id)
    if provider is None:
        raise ResourceNotFoundError("AI 服务商不存在。")
    if await repo.model_remote_id_exists(session, provider_id, payload.remote_model_id):
        raise ConflictError(_REMOTE_ID_TAKEN, details=[ErrorDetail(field="remote_model_id", reason="标识已被占用。")])
    has_default = await repo.get_default_model(session) is not None
    model = AiModel(
        provider_id=provider_id,
        name=payload.name,
        remote_model_id=payload.remote_model_id,
        is_enabled=payload.is_enabled,
        is_default=(not has_default) and payload.is_enabled and provider.is_enabled,
    )
    await repo.add(session, model)
    await session.commit()
    await session.refresh(model)
    return ModelRead.model_validate(model)


async def update_model(session: AsyncSession, model_id: uuid.UUID, payload: ModelUpdate) -> ModelRead:
    """局部更新模型；未提交字段保持原值。

    参数:
        session: 当前会话。
        model_id: 模型主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ModelRead: 更新后的模型。

    异常:
        ResourceNotFoundError: 模型不存在。
        ConflictError: 停用默认模型、远端标识重复或版本过期。
        ValidationFailedError: 必填字段被提交为 null。
    """
    model = await repo.get_model(session, model_id)
    if model is None:
        raise ResourceNotFoundError("AI 模型不存在。")

    provided = payload.model_fields_set
    updates: dict[str, Any] = {}
    if "name" in provided:
        if payload.name is None:
            raise ValidationFailedError("模型名称不能为空。", details=[ErrorDetail(field="name", reason="不能为空。")])
        updates["name"] = payload.name
    if "remote_model_id" in provided:
        if payload.remote_model_id is None:
            raise ValidationFailedError(
                "远端模型标识不能为空。", details=[ErrorDetail(field="remote_model_id", reason="不能为空。")]
            )
        if await repo.model_remote_id_exists(session, model.provider_id, payload.remote_model_id, exclude_id=model.id):
            raise ConflictError(
                _REMOTE_ID_TAKEN, details=[ErrorDetail(field="remote_model_id", reason="标识已被占用。")]
            )
        updates["remote_model_id"] = payload.remote_model_id
    if "is_enabled" in provided and payload.is_enabled is not None:
        if not payload.is_enabled and model.is_default:
            raise ConflictError("默认模型不能被停用，请先设置其他启用模型为默认。")
        updates["is_enabled"] = payload.is_enabled

    if updates:
        try:
            await apply_versioned_update(session, model, payload.version, updates)
        except IntegrityError as error:
            await session.rollback()
            raise ConflictError(_REMOTE_ID_TAKEN) from error
        await session.commit()
    elif model.version != payload.version:
        raise ConflictError(
            "记录已被更新，请刷新后重试。",
            details=[ErrorDetail(field="version", reason=f"当前版本为 {model.version}，提交的是 {payload.version}。")],
        )
    await session.refresh(model)
    return ModelRead.model_validate(model)


async def set_default_model(session: AsyncSession, model_id: uuid.UUID) -> ModelRead:
    """把指定启用模型设为唯一默认模型。

    参数:
        session: 当前会话。
        model_id: 目标模型主键。

    返回:
        ModelRead: 设置后的模型。

    异常:
        ResourceNotFoundError: 模型或所属服务商不存在。
        ConflictError: 模型或其服务商已停用。

    注意:
        加锁顺序固定为"先当前默认行、后目标行"，并在同一事务内先清除旧默认再设置新默认，
        否则部分唯一索引会在设置新默认时立即判定冲突。锁与单事务共同保证并发切换不会
        产生两个默认模型。
    """
    model = await repo.get_model_for_update(session, model_id)
    if model is None:
        raise ResourceNotFoundError("AI 模型不存在。")
    if not model.is_enabled:
        raise ConflictError("已停用的模型不能被设为默认，请先启用该模型。")
    provider = await repo.get_provider(session, model.provider_id)
    if provider is None:
        raise ResourceNotFoundError("AI 服务商不存在。")
    if not provider.is_enabled:
        raise ConflictError("所属服务商已停用，不能设为默认模型。")

    current = await repo.get_default_model(session, for_update=True)
    if current is not None and current.id != model.id:
        current.is_default = False
        # 先落库清除旧标记，避免新的 is_default 与旧默认同时为真而触发唯一索引冲突。
        await session.flush()
    model.is_default = True
    await session.commit()
    await session.refresh(model)
    return ModelRead.model_validate(model)


async def delete_model(session: AsyncSession, model_id: uuid.UUID, payload: DeleteConfirm) -> None:
    """删除模型。

    参数:
        session: 当前会话。
        model_id: 模型主键。
        payload: 删除确认。

    异常:
        ValidationFailedError: 未确认删除。
        ResourceNotFoundError: 模型不存在。
        ConflictError: 目标是默认模型，必须先改默认。
    """
    if not payload.confirmed:
        raise ValidationFailedError("请确认删除模型；删除后不可恢复。")
    model = await repo.get_model(session, model_id)
    if model is None:
        raise ResourceNotFoundError("AI 模型不存在。")
    if model.is_default:
        raise ConflictError("默认模型不能被删除，请先设置其他启用模型为默认。")
    await repo.remove(session, model)
    await session.commit()


async def test_connection(session: AsyncSession, model_id: uuid.UUID) -> ConnectionTestRead:
    """测试已保存模型的连通性。

    参数:
        session: 当前会话。
        model_id: 模型主键。

    返回:
        ConnectionTestRead: 最小协议请求成功时为 `ok=True`。

    异常:
        ResourceNotFoundError: 模型或服务商不存在。
        ConflictError: 服务商或模型已停用，或凭据加密根密钥缺失。
        ValidationFailedError: 上游不可用或响应不符合 OpenAI 兼容格式。

    注意:
        读取配置后先结束数据库事务再等待网络；只发送最小协议请求，
        不携带简历、档案、职位或匹配数据，也不改变任何配置或业务数据。
    """
    model = await repo.get_model(session, model_id)
    if model is None:
        raise ResourceNotFoundError("AI 模型不存在。")
    provider = await repo.get_provider(session, model.provider_id)
    if provider is None:
        raise ResourceNotFoundError("AI 服务商不存在。")
    if not provider.is_enabled or not model.is_enabled:
        raise ConflictError("服务商或模型已停用，不能测试连接。")
    api_key = _cipher().decrypt(provider.api_key_ciphertext) if provider.api_key_ciphertext is not None else None
    config = gateway.ResolvedAiModel(
        base_url=provider.base_url,
        remote_model_id=model.remote_model_id,
        api_key=api_key,
    )
    # 外部 HTTP 必须在事务之外进行，避免长事务占用连接（见 ADR 0002）。
    await session.rollback()
    await gateway.check_connection(config)
    return ConnectionTestRead(ok=True)


async def resolve_default_model(session: AsyncSession, settings: Settings) -> gateway.ResolvedAiModel:
    """解析当前唯一默认启用模型，返回仅存在于内存的请求配置。

    参数:
        session: 当前会话。
        settings: 应用配置，用于解析凭据加密根密钥。

    返回:
        gateway.ResolvedAiModel: 默认模型的基地址、远端模型标识与解密后的凭据。

    异常:
        ConflictError: 尚未配置默认模型、模型或其服务商已停用，或根密钥缺失/无法解密。

    注意:
        本函数只读取配置并解密凭据，不修改任何数据；调用方必须在等待外部 HTTP 前
        再结束一次读事务，使网络等待期间不持有数据库事务（见 ADR 0002）。
    """
    model = await repo.get_default_model(session)
    if model is None or not model.is_enabled:
        raise ConflictError("尚未配置默认 AI 模型，请先在 AI 模型配置中启用一个模型。")
    provider = await repo.get_provider(session, model.provider_id)
    if provider is None or not provider.is_enabled:
        raise ConflictError("默认 AI 模型的服务商已停用，请先在 AI 模型配置中启用。")
    api_key = (
        CredentialCipher.from_settings(settings).decrypt(provider.api_key_ciphertext)
        if provider.api_key_ciphertext is not None
        else None
    )
    return gateway.ResolvedAiModel(
        base_url=provider.base_url,
        remote_model_id=model.remote_model_id,
        api_key=api_key,
    )
