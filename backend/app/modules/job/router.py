"""Job 领域 HTTP 接口：手工职位录入与 JD 快照维护。"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.responses import ApiResponse, success

from . import repository, service
from .schemas import (
    JobListItem,
    JobManualCreate,
    JobOpportunityRead,
    JobOpportunityUpdate,
    JobSnapshotCreate,
    JobSnapshotRead,
)

router = APIRouter(prefix="/jobs", tags=["job"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "/{opportunity_id}/snapshots",
    summary="历史 JD 快照",
    description="单人本地读取；返回原始历史内容，机会不存在返回 404。",
    response_model=ApiResponse[list[JobSnapshotRead]],
)
async def list_snapshots(session: SessionDep, opportunity_id: uuid.UUID) -> ApiResponse[list[JobSnapshotRead]]:
    """读取机会的全部不可变 JD 内容。"""
    await service.require_opportunity(session, opportunity_id)
    return success(
        [JobSnapshotRead.model_validate(row) for row in await repository.list_snapshots(session, opportunity_id)]
    )


@router.get(
    "",
    summary="列出职位机会",
    description="返回人工维护的职位摘要与最近 JD 时间，不返回完整 JD。",
    response_model=ApiResponse[list[JobListItem]],
)
async def list_jobs(session: SessionDep) -> ApiResponse[list[JobListItem]]:
    """读取职位列表。"""
    return success(await service.list_jobs(session))


@router.post(
    "",
    summary="手工录入职位与 JD",
    description="原子创建公司、职位机会、手工页面与不可变原始 JD 快照；不会调用 AI 解析。",
    response_model=ApiResponse[JobOpportunityRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_job(session: SessionDep, payload: JobManualCreate) -> ApiResponse[JobOpportunityRead]:
    """创建手工职位记录。"""
    return success(await service.create_manual_job(session, payload))


@router.get(
    "/{opportunity_id}",
    summary="读取职位详情",
    description="返回公司、关联页面及最近 JD 快照；职位不存在时返回 404。",
    response_model=ApiResponse[JobOpportunityRead],
)
async def get_job(session: SessionDep, opportunity_id: uuid.UUID) -> ApiResponse[JobOpportunityRead]:
    """读取职位聚合详情。"""
    return success(await service.get_opportunity_detail(session, opportunity_id))


@router.patch(
    "/{opportunity_id}",
    summary="更新职位机会",
    description="更新标题、地点、雇佣类型、状态或备注；必须提交当前 version，过期返回 409。",
    response_model=ApiResponse[JobOpportunityRead],
)
async def update_job(
    session: SessionDep, opportunity_id: uuid.UUID, payload: JobOpportunityUpdate
) -> ApiResponse[JobOpportunityRead]:
    """局部更新可编辑职位字段。"""
    return success(await service.update_opportunity(session, opportunity_id, payload))


@router.post(
    "/{opportunity_id}/postings/{posting_id}/snapshots",
    summary="保存新的 JD 快照",
    description="保存同一页面的新原始 JD；相同内容不会重复创建，暂不触发 AI 解析。",
    response_model=ApiResponse[JobSnapshotRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_snapshot(
    session: SessionDep, opportunity_id: uuid.UUID, posting_id: uuid.UUID, payload: JobSnapshotCreate
) -> ApiResponse[JobSnapshotRead]:
    """保存新的不可变 JD 快照。"""
    return success(
        JobSnapshotRead.model_validate(await service.create_snapshot(session, opportunity_id, posting_id, payload))
    )
