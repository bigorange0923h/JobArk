"""单人申请管理接口，所有操作只记录本地事实，不调用招聘平台。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.responses import ApiResponse, success

from . import service
from .schemas import ApplicationCreate, ApplicationDetail, ApplicationMaterials, ApplicationRead, ApplicationTransition

router = APIRouter(prefix="/applications", tags=["application"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "",
    summary="申请列表",
    description="单人本地申请摘要，不触发外部投递。",
    response_model=ApiResponse[list[ApplicationRead]],
)
async def list_applications(session: SessionDep) -> ApiResponse[list[ApplicationRead]]:
    """返回申请列表及统一元信息。"""
    return success(await service.list_applications(session))


@router.post(
    "",
    summary="创建申请记录",
    description=(
        "创建可调整材料的准备记录；已有申请返回 409 + DUPLICATE_APPLICATION，"
        "用户确认后携带 confirm_repeat 创建新尝试；引用无效返回 404/422。"
    ),
    response_model=ApiResponse[ApplicationDetail],
    status_code=201,
)
async def create_application(session: SessionDep, payload: ApplicationCreate) -> ApiResponse[ApplicationDetail]:
    """创建本地记录和首个事件，不代表已完成外部投递。"""
    return success(await service.create(session, payload))


@router.get(
    "/{application_id}",
    summary="申请时间线",
    description="读取输入引用、事件和允许的后续状态；不存在返回 404。",
    response_model=ApiResponse[ApplicationDetail],
)
async def get_application(session: SessionDep, application_id: UUID) -> ApiResponse[ApplicationDetail]:
    """返回完整申请时间线。"""
    return success(await service.detail(session, application_id))


@router.post(
    "/{application_id}/events",
    summary="记录状态变更",
    description="要求当前 version；APPLIED 需人工确认，非法跳转/过期返回 409，缺少确认返回 422。",
    response_model=ApiResponse[ApplicationDetail],
)
async def change_status(
    session: SessionDep, application_id: UUID, payload: ApplicationTransition
) -> ApiResponse[ApplicationDetail]:
    """原子创建状态事件并更新投影。"""
    return success(await service.transition(session, application_id, payload))


@router.patch(
    "/{application_id}/materials",
    summary="调整申请准备材料",
    description="要求当前 version；未锁定准备阶段可换 JD 或正式简历，就绪变更后重新核验。"
    "不存在返回 404，过期/已锁定/已结束返回 409，归属无效返回 422；无外部副作用。",
    response_model=ApiResponse[ApplicationDetail],
)
async def change_materials(
    session: SessionDep,
    application_id: UUID,
    payload: ApplicationMaterials,
) -> ApiResponse[ApplicationDetail]:
    """原子保存材料前后引用、必要状态变更及事件历史。"""
    return success(await service.change_materials(session, application_id, payload))
