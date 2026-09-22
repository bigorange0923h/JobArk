"""从申请事件复算统计，不保存另一份业务事实。"""

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.responses import ApiResponse, success
from app.modules.application.models import Application, ApplicationEvent, ApplicationStatus
from app.modules.job.models import JobOpportunity, JobPosting, JobSnapshot

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class Metric(BaseModel):
    """带明确口径的计数项。"""

    label: str = Field(description="分组标签。")
    count: int = Field(description="申请尝试数或职位数。")


class VersionConversion(BaseModel):
    """按简历版本汇总的尝试和结果样本。"""

    resume_version_id: str
    attempts: int
    applied: int
    interviewed: int
    offered: int


class DashboardRead(BaseModel):
    """统计口径：事件曾到达阶段，日期按 UTC；转化按申请尝试计。"""

    pending_jobs: int
    application_count: int
    funnel: list[Metric]
    sources: list[Metric]
    trend: list[Metric]
    versions: list[VersionConversion]


@router.get(
    "",
    summary="求职统计",
    description="单人本地投影；漏斗按曾到达阶段，趋势按 UTC 投递日期，版本统计以申请尝试为样本。",
    response_model=ApiResponse[DashboardRead],
)
async def dashboard(session: Annotated[AsyncSession, Depends(get_session)]) -> ApiResponse[DashboardRead]:
    """读取事件并复算计数；空库返回零和空列表，无写入副作用。"""
    applications = (await session.scalars(select(Application))).all()
    events = (await session.scalars(select(ApplicationEvent))).all()
    reached = {app.id: {event.to_status for event in events if event.application_id == app.id} for app in applications}
    stages = [
        ApplicationStatus.APPLIED,
        ApplicationStatus.CONTACTED,
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.OFFERED,
    ]
    funnel = [Metric(label=stage.value, count=sum(stage in values for values in reached.values())) for stage in stages]
    trend = Counter(
        event.occurred_at.date().isoformat() for event in events if event.to_status == ApplicationStatus.APPLIED
    )
    sources = Counter(
        (
            await session.scalars(
                select(JobPosting.source)
                .join(JobSnapshot)
                .join(Application, Application.job_snapshot_id == JobSnapshot.id)
            )
        ).all()
    )
    versions: list[VersionConversion] = []
    for version in sorted({app.resume_version_id for app in applications}, key=str):
        ids = [app.id for app in applications if app.resume_version_id == version]
        versions.append(
            VersionConversion(
                resume_version_id=str(version),
                attempts=len(ids),
                applied=sum(ApplicationStatus.APPLIED in reached[key] for key in ids),
                interviewed=sum(ApplicationStatus.INTERVIEWING in reached[key] for key in ids),
                offered=sum(ApplicationStatus.OFFERED in reached[key] for key in ids),
            )
        )
    jobs = (await session.scalars(select(JobOpportunity))).all()
    linked = {app.job_opportunity_id for app in applications}
    return success(
        DashboardRead(
            pending_jobs=sum(job.status == "ACTIVE" and job.id not in linked for job in jobs),
            application_count=len(applications),
            funnel=funnel,
            sources=[Metric(label=str(key), count=value) for key, value in sorted(sources.items())],
            trend=[Metric(label=key, count=value) for key, value in sorted(trend.items())],
            versions=versions,
        )
    )
