"""AI 模型配置的 HTTP 接口。

约定：

- 所有响应包裹在统一契约中（见 ADR 0001），失败由统一异常处理器构造，这里不出现 `try/except`。
- 路由只做参数绑定与响应包装，业务规则全在 `service.py`。
- 凭据**只写不读**：读取 DTO 永远只含掩码与"是否已配置"，删除与连接测试都不会回显凭据。
- 单用户本地工具，V1 没有认证与权限；删除类操作要求显式 `confirmed`，未确认为 422。

主要错误映射：

- `RESOURCE_NOT_FOUND`：服务商或模型不存在。
- `VALIDATION_ERROR`：字段校验失败、地址不安全、未确认删除。
- `CONFLICT`：名称或远端模型标识重复、版本过期、默认模型不可停用/删除、服务商停用或删除时仍有默认模型、根密钥缺失。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.responses import ApiResponse, success

from . import service
from .schemas.config import (
    ConnectionTestRead,
    DeleteConfirm,
    DeletedRead,
    ModelCreate,
    ModelRead,
    ModelUpdate,
    ProviderCreate,
    ProviderRead,
    ProviderUpdate,
)

router = APIRouter(prefix="/ai", tags=["ai"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --------------------------------------------------------------------------------------------
# 服务商
# --------------------------------------------------------------------------------------------


@router.get(
    "/providers",
    summary="列出 AI 服务商",
    description="返回全部服务商及其模型配置，只含掩码与是否已配置凭据，绝不返回 API Key 明文或密文。",
    response_model=ApiResponse[list[ProviderRead]],
)
async def list_providers(session: SessionDep) -> ApiResponse[list[ProviderRead]]:
    """列出服务商与模型配置。

    参数:
        session: 请求级数据库会话。

    返回:
        ApiResponse[list[ProviderRead]]: 服务商配置列表；空列表表示尚未配置。
    """
    return success(await service.list_providers(session))


@router.post(
    "/providers",
    summary="新增 AI 服务商",
    description=(
        "保存 OpenAI 兼容服务商。接口地址仅允许 HTTPS 或本地回环 HTTP，"
        "且不能包含用户名、密码、查询参数或片段；不安全地址返回 422。"
        "提交的 API Key 以可逆密文入库，读取时只返回掩码。名称重复返回 409。"
    ),
    response_model=ApiResponse[ProviderRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(session: SessionDep, payload: ProviderCreate) -> ApiResponse[ProviderRead]:
    """新增服务商。

    参数:
        session: 请求级数据库会话。
        payload: 服务商配置与可选 API Key。

    返回:
        ApiResponse[ProviderRead]: 新建服务商。

    异常:
        VALIDATION_ERROR: 字段校验失败或接口地址不安全。
        CONFLICT: 名称重复，或非 LOCAL 环境缺少凭据加密根密钥。
    """
    return success(await service.create_provider(session, payload))


@router.patch(
    "/providers/{provider_id}",
    summary="更新 AI 服务商",
    description=(
        "局部更新服务商；必须提交当前 version，版本过期返回 409。"
        "未提交或提交空的 api_key 表示保留已有密文，只有提交新值才替换。"
        "存在默认模型时不允许停用服务商，返回 409。"
    ),
    response_model=ApiResponse[ProviderRead],
)
async def update_provider(session: SessionDep, provider_id: UUID, payload: ProviderUpdate) -> ApiResponse[ProviderRead]:
    """局部更新服务商。

    参数:
        session: 请求级数据库会话。
        provider_id: 服务商主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ApiResponse[ProviderRead]: 更新后的服务商。

    异常:
        RESOURCE_NOT_FOUND: 服务商不存在。
        VALIDATION_ERROR: 字段校验失败或接口地址不安全。
        CONFLICT: 名称重复、版本过期，或在存在默认模型时停用。
    """
    return success(await service.update_provider(session, provider_id, payload))


@router.delete(
    "/providers/{provider_id}",
    summary="删除 AI 服务商",
    description=(
        "删除服务商及其全部模型配置，API Key 不可恢复；必须提交 confirmed=true，未确认返回 422。"
        "其下仍有默认模型时返回 409，必须先改默认，避免静默失去唯一可用模型。"
    ),
    response_model=ApiResponse[DeletedRead],
)
async def delete_provider(session: SessionDep, provider_id: UUID, payload: DeleteConfirm) -> ApiResponse[DeletedRead]:
    """删除服务商及其模型。

    参数:
        session: 请求级数据库会话。
        provider_id: 服务商主键。
        payload: 删除确认。

    返回:
        ApiResponse[DeletedRead]: 被删除服务商的主键。

    异常:
        RESOURCE_NOT_FOUND: 服务商不存在。
        VALIDATION_ERROR: 未确认删除。
        CONFLICT: 其下仍有默认模型。
    """
    await service.delete_provider(session, provider_id, payload)
    return success(DeletedRead(id=provider_id))


# --------------------------------------------------------------------------------------------
# 模型
# --------------------------------------------------------------------------------------------


@router.post(
    "/providers/{provider_id}/models",
    summary="新增 AI 模型",
    description=(
        "在服务商下新增模型；模型不携带 API Key，凭据始终复用所属服务商。"
        "首个启用模型自动成为唯一默认模型；同一服务商下远端模型标识重复返回 409。"
    ),
    response_model=ApiResponse[ModelRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_model(session: SessionDep, provider_id: UUID, payload: ModelCreate) -> ApiResponse[ModelRead]:
    """在服务商下新增模型。

    参数:
        session: 请求级数据库会话。
        provider_id: 所属服务商主键。
        payload: 模型配置。

    返回:
        ApiResponse[ModelRead]: 新建模型。

    异常:
        RESOURCE_NOT_FOUND: 服务商不存在。
        CONFLICT: 远端模型标识重复。
    """
    return success(await service.create_model(session, provider_id, payload))


@router.patch(
    "/models/{model_id}",
    summary="更新 AI 模型",
    description=(
        "局部更新模型；必须提交当前 version。默认模型不能被直接停用，返回 409；"
        "远端模型标识在同一服务商内重复返回 409。默认标记只能通过设为默认接口变更。"
    ),
    response_model=ApiResponse[ModelRead],
)
async def update_model(session: SessionDep, model_id: UUID, payload: ModelUpdate) -> ApiResponse[ModelRead]:
    """局部更新模型。

    参数:
        session: 请求级数据库会话。
        model_id: 模型主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ApiResponse[ModelRead]: 更新后的模型。

    异常:
        RESOURCE_NOT_FOUND: 模型不存在。
        CONFLICT: 停用默认模型、远端标识重复或版本过期。
    """
    return success(await service.update_model(session, model_id, payload))


@router.post(
    "/models/{model_id}/default",
    summary="设为默认模型",
    description=(
        "把指定启用模型设为唯一默认模型；切换在单个事务内清除旧默认。"
        "模型或其服务商已停用返回 409；服务端 AI 调用一律使用该默认模型。"
    ),
    response_model=ApiResponse[ModelRead],
)
async def set_default_model(session: SessionDep, model_id: UUID) -> ApiResponse[ModelRead]:
    """设置唯一默认模型。

    参数:
        session: 请求级数据库会话。
        model_id: 目标模型主键。

    返回:
        ApiResponse[ModelRead]: 设置后的模型。

    异常:
        RESOURCE_NOT_FOUND: 模型或服务商不存在。
        CONFLICT: 模型或服务商已停用。
    """
    return success(await service.set_default_model(session, model_id))


@router.post(
    "/models/{model_id}/test",
    summary="测试 AI 模型连接",
    description=(
        "使用已保存配置发送一次最小 OpenAI 兼容协议请求，验证地址与凭据是否可用。"
        "不发送简历、档案、职位或匹配数据，不产生业务事实，也不改变默认状态或凭据。"
        "上游失败返回 422 并附带安全文案与请求标识。"
    ),
    response_model=ApiResponse[ConnectionTestRead],
)
async def test_connection(session: SessionDep, model_id: UUID) -> ApiResponse[ConnectionTestRead]:
    """测试模型连通性。

    参数:
        session: 请求级数据库会话。
        model_id: 模型主键。

    返回:
        ApiResponse[ConnectionTestRead]: 请求成功时 `ok=True`。

    异常:
        RESOURCE_NOT_FOUND: 模型或服务商不存在。
        CONFLICT: 服务商或模型已停用，或凭据根密钥缺失。
        VALIDATION_ERROR: 上游不可用或响应不符合 OpenAI 兼容格式。
    """
    return success(await service.test_connection(session, model_id))


@router.delete(
    "/models/{model_id}",
    summary="删除 AI 模型",
    description="删除模型配置；必须提交 confirmed=true，未确认返回 422。默认模型不能被删除，返回 409。",
    response_model=ApiResponse[DeletedRead],
)
async def delete_model(session: SessionDep, model_id: UUID, payload: DeleteConfirm) -> ApiResponse[DeletedRead]:
    """删除模型。

    参数:
        session: 请求级数据库会话。
        model_id: 模型主键。
        payload: 删除确认。

    返回:
        ApiResponse[DeletedRead]: 被删除模型的主键。

    异常:
        RESOURCE_NOT_FOUND: 模型不存在。
        VALIDATION_ERROR: 未确认删除。
        CONFLICT: 目标是默认模型。
    """
    await service.delete_model(session, model_id, payload)
    return success(DeletedRead(id=model_id))
