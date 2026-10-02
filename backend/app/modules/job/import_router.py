"""本地职位内容导入接口；候选预览与明确确认分别执行。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.responses import ApiResponse, success

from . import import_service
from .import_schemas import ImportConfirm, ImportConfirmation, ImportPreview, ImportRead

router = APIRouter(prefix="/job-imports", tags=["job"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/preview",
    summary="预览招聘平台内容",
    status_code=201,
    response_model=ApiResponse[ImportRead],
    description=(
        "本地解析用户提供的四站详情链接与正文/HTML，不访问网站、不外发 AI。"
        "只保存候选；非法链接、多个职位、无正文返回 422。"
    ),
)
async def preview(session: SessionDep, payload: ImportPreview) -> ApiResponse[ImportRead]:
    """保存必要候选和来源哈希；正式职位仍需单独明确确认。"""
    return success(await import_service.preview(session, payload))


@router.get(
    "/{candidate_id}",
    summary="读取职位导入候选",
    response_model=ApiResponse[ImportRead],
    description="单人本地读取冻结候选与确认状态，无外部副作用；不存在返回 404。",
)
async def read(session: SessionDep, candidate_id: UUID) -> ApiResponse[ImportRead]:
    """读取已保存候选；不重新解析或读取平台页面。"""
    return success(import_service.read_candidate(await import_service.get_candidate(session, candidate_id)))


@router.post(
    "/{candidate_id}/confirm",
    summary="确认职位内容导入",
    response_model=ApiResponse[ImportConfirmation],
    description=(
        "需 confirm=true 和候选 version；原子创建职位或更新已有 JD，返回不可变产物回执。"
        "同内容重试幂等。不投递；缺确认/必填返回 422，不存在 404，"
        "过期/版本/重复内容或锁超时冲突 409。"
    ),
)
async def confirm(session: SessionDep, candidate_id: UUID, payload: ImportConfirm) -> ApiResponse[ImportConfirmation]:
    """用户确认后写入来源页面与不可变快照，保存人工修订审计。"""
    return success(await import_service.confirm(session, candidate_id, payload))
