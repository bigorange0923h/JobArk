"""申请事务服务；事件是状态历史的唯一入口。"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ResourceNotFoundError, ValidationFailedError
from app.core.versioning import apply_versioned_update
from app.modules.job.models import JobOpportunity, JobPosting, JobSnapshot
from app.modules.resume.models import ResumeVersion

from .models import Application, ApplicationEvent
from .models import ApplicationStatus as S
from .schemas import ApplicationCreate, ApplicationDetail, ApplicationEventRead, ApplicationRead, ApplicationTransition

TRANSITIONS: dict[S, tuple[S, ...]] = {
    S.SAVED: (S.PREPARING, S.APPLIED, S.WITHDRAWN, S.CLOSED),
    S.PREPARING: (S.READY_TO_APPLY, S.APPLIED, S.WITHDRAWN, S.CLOSED),
    S.READY_TO_APPLY: (S.APPLIED, S.WITHDRAWN, S.CLOSED),
    S.APPLIED: (S.CONTACTED, S.INTERVIEWING, S.REJECTED, S.WITHDRAWN, S.CLOSED),
    S.CONTACTED: (S.INTERVIEWING, S.REJECTED, S.WITHDRAWN, S.CLOSED),
    S.INTERVIEWING: (S.OFFERED, S.REJECTED, S.WITHDRAWN, S.CLOSED),
    S.OFFERED: (S.WITHDRAWN, S.CLOSED),
    S.REJECTED: (),
    S.WITHDRAWN: (),
    S.CLOSED: (),
}


async def list_applications(session: AsyncSession) -> list[ApplicationRead]:
    """读取所有申请摘要，最近创建在前；无写入副作用。"""
    rows = await session.scalars(select(Application).order_by(Application.created_at.desc(), Application.id))
    return [ApplicationRead.model_validate(row) for row in rows]


async def detail(session: AsyncSession, application_id: UUID) -> ApplicationDetail:
    """读取申请与完整事件；不存在返回 404。"""
    entity = await session.get(Application, application_id)
    if entity is None:
        raise ResourceNotFoundError("申请不存在。")
    events = await session.scalars(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == entity.id)
        .order_by(ApplicationEvent.sequence_no)
    )
    return ApplicationDetail(
        **ApplicationRead.model_validate(entity).model_dump(),
        events=[ApplicationEventRead.model_validate(item) for item in events],
        allowed_statuses=list(TRANSITIONS[entity.current_status]),
    )


async def create(session: AsyncSession, payload: ApplicationCreate) -> ApplicationDetail:
    """锁定机会后分配尝试编号，验证输入归属并原子保存初始事件。"""
    job = await session.scalar(
        select(JobOpportunity).where(JobOpportunity.id == payload.job_opportunity_id).with_for_update()
    )
    if job is None:
        raise ResourceNotFoundError("职位不存在。")
    snapshot = await session.scalar(
        select(JobSnapshot)
        .join(JobPosting)
        .where(JobSnapshot.id == payload.job_snapshot_id, JobPosting.opportunity_id == job.id)
    )
    if snapshot is None:
        raise ValidationFailedError("JD 快照不属于该职位。")
    if await session.get(ResumeVersion, payload.resume_version_id) is None:
        raise ResourceNotFoundError("简历版本不存在。")
    previous = await session.scalar(
        select(func.max(Application.attempt_no)).where(Application.job_opportunity_id == job.id)
    )
    if previous and not payload.confirm_repeat:
        raise ConflictError("已有申请记录，请确认是否创建新的申请尝试。")
    entity = Application(
        job_opportunity_id=job.id,
        job_snapshot_id=snapshot.id,
        resume_version_id=payload.resume_version_id,
        attempt_no=(previous or 0) + 1,
        current_status=S.SAVED,
    )
    session.add(entity)
    await session.flush()
    session.add(
        ApplicationEvent(
            application_id=entity.id,
            sequence_no=1,
            event_type="CREATED",
            from_status=None,
            to_status=S.SAVED,
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return await detail(session, entity.id)


async def transition(session: AsyncSession, application_id: UUID, payload: ApplicationTransition) -> ApplicationDetail:
    """验证合法边、确认与版本；事件和状态投影在同一事务写入。"""
    entity = await session.get(Application, application_id)
    if entity is None:
        raise ResourceNotFoundError("申请不存在。")
    before = entity.current_status
    if payload.status not in TRANSITIONS[before]:
        raise ConflictError("当前阶段不允许此状态变更。")
    if payload.status == S.APPLIED and not payload.confirm_applied:
        raise ValidationFailedError("请确认已在外部平台完成投递。")
    await apply_versioned_update(session, entity, payload.version, {"current_status": payload.status})
    session.add(
        ApplicationEvent(
            application_id=entity.id,
            sequence_no=entity.version,
            event_type="STATUS_CHANGED",
            from_status=before,
            to_status=payload.status,
            occurred_at=datetime.now(UTC),
            notes=payload.notes,
        )
    )
    await session.commit()
    return await detail(session, entity.id)
