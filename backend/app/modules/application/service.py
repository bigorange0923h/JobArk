"""申请事务服务：材料准备可调整，首次已投递确认后永久锁定。"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DuplicateApplicationError, ResourceNotFoundError, ValidationFailedError
from app.core.versioning import apply_versioned_update
from app.modules.job.models import JobOpportunity, JobPosting, JobSnapshot
from app.modules.job.strategy import current as current_exclusion
from app.modules.resume.models import ResumeVersion

from .models import Application, ApplicationEvent
from .models import ApplicationStatus as S
from .schemas import (
    ApplicationCreate,
    ApplicationDetail,
    ApplicationEventRead,
    ApplicationMaterials,
    ApplicationRead,
    ApplicationTransition,
    AppliedPayload,
    CreatedPayload,
    MaterialReferences,
    MaterialsChangedPayload,
)

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
PREPARATION = (S.SAVED, S.PREPARING, S.READY_TO_APPLY)


def _inputs(entity: Application) -> MaterialReferences:
    """取当前输入引用用于事件冻结；不会读取可变正文。"""
    return MaterialReferences(job_snapshot_id=entity.job_snapshot_id, resume_version_id=entity.resume_version_id)


async def _locked_application(session: AsyncSession, application_id: UUID) -> Application:
    """锁定申请并读取最新投影；不存在返回 404，并发由版本号明确判定。"""
    entity = await session.scalar(
        select(Application)
        .where(Application.id == application_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if entity is None:
        raise ResourceNotFoundError("申请不存在。")
    return entity


async def _validate_materials(
    session: AsyncSession,
    opportunity_id: UUID,
    snapshot_id: UUID,
    resume_version_id: UUID | None,
) -> None:
    """校验准备输入的存在及归属；空正式简历仅用于准备阶段。"""
    snapshot = await session.scalar(
        select(JobSnapshot)
        .join(JobPosting, JobSnapshot.posting_id == JobPosting.id)
        .where(JobSnapshot.id == snapshot_id, JobPosting.opportunity_id == opportunity_id)
    )
    if snapshot is None:
        raise ValidationFailedError("JD 快照不属于该职位。")
    if resume_version_id is not None and await session.get(ResumeVersion, resume_version_id) is None:
        raise ResourceNotFoundError("简历版本不存在。")


async def _append_event(
    session: AsyncSession,
    entity: Application,
    kind: str,
    before: S | None,
    payload: dict[str, Any],
    notes: str | None = None,
) -> None:
    """按申请分配独立事件序号；载荷按事件类型校验，与投影同一事务写入。"""
    if kind == "CREATED":
        payload = CreatedPayload.model_validate(payload).model_dump(mode="json")
    elif kind == "MATERIALS_CHANGED":
        payload = MaterialsChangedPayload.model_validate(payload).model_dump(mode="json")
    elif kind == "APPLIED":
        payload = AppliedPayload.model_validate(payload).model_dump(mode="json")
        if not payload["confirm_applied"]:
            raise ValidationFailedError("请确认已完成外部投递。")
    elif kind != "STATUS_CHANGED" or payload:
        raise ValidationFailedError("申请事件类型或载荷无效。")
    sequence = await session.scalar(
        select(func.max(ApplicationEvent.sequence_no)).where(ApplicationEvent.application_id == entity.id)
    )
    session.add(
        ApplicationEvent(
            application_id=entity.id,
            sequence_no=(sequence or 0) + 1,
            event_type=kind,
            from_status=before,
            to_status=entity.current_status,
            occurred_at=datetime.now(UTC),
            payload_json=payload,
            notes=notes,
        )
    )


async def list_applications(session: AsyncSession) -> list[ApplicationRead]:
    """读取申请摘要，最近创建在前；无写入副作用。"""
    rows = await session.scalars(select(Application).order_by(Application.created_at.desc(), Application.id))
    return [ApplicationRead.model_validate(row) for row in rows]


async def detail(session: AsyncSession, application_id: UUID) -> ApplicationDetail:
    """读取申请、材料锁定与完整事件；不存在返回 404。"""
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
    """锁定机会分配尝试编号，原子保存准备输入与首事件；不代表已投递。"""
    job = await session.scalar(
        select(JobOpportunity).where(JobOpportunity.id == payload.job_opportunity_id).with_for_update()
    )
    if job is None:
        raise ResourceNotFoundError("职位不存在。")
    await _validate_materials(session, job.id, payload.job_snapshot_id, payload.resume_version_id)
    previous = await session.scalar(
        select(func.max(Application.attempt_no)).where(Application.job_opportunity_id == job.id)
    )
    if previous and not payload.confirm_repeat:
        raise DuplicateApplicationError()
    entity = Application(
        job_opportunity_id=job.id,
        job_snapshot_id=payload.job_snapshot_id,
        resume_version_id=payload.resume_version_id,
        attempt_no=(previous or 0) + 1,
        current_status=S.SAVED,
    )
    session.add(entity)
    await session.flush()
    await _append_event(session, entity, "CREATED", None, {"inputs": _inputs(entity).model_dump(mode="json")})
    await session.commit()
    return await detail(session, entity.id)


async def change_materials(
    session: AsyncSession,
    application_id: UUID,
    payload: ApplicationMaterials,
) -> ApplicationDetail:
    """只调整未锁定准备材料；就绪变更返回准备中，前后输入与状态一起留痕。"""
    entity = await _locked_application(session, application_id)
    if entity.material_locked_at is not None or entity.current_status not in PREPARATION:
        raise ConflictError("该申请已锁定材料或结束，不能替换 JD 或简历版本。")
    await _validate_materials(session, entity.job_opportunity_id, payload.job_snapshot_id, payload.resume_version_id)
    if entity.version != payload.version:
        raise ConflictError("申请版本已过期，请刷新后重试。")
    before_inputs = _inputs(entity)
    if (
        before_inputs.job_snapshot_id == payload.job_snapshot_id
        and before_inputs.resume_version_id == payload.resume_version_id
    ):
        return await detail(session, entity.id)
    before_status = entity.current_status
    await apply_versioned_update(
        session,
        entity,
        payload.version,
        {
            "job_snapshot_id": payload.job_snapshot_id,
            "resume_version_id": payload.resume_version_id,
            "current_status": S.PREPARING if before_status == S.READY_TO_APPLY else before_status,
        },
    )
    await _append_event(
        session,
        entity,
        "MATERIALS_CHANGED",
        before_status,
        {
            "before": before_inputs.model_dump(mode="json"),
            "after": _inputs(entity).model_dump(mode="json"),
        },
    )
    await session.commit()
    return await detail(session, entity.id)


async def transition(session: AsyncSession, application_id: UUID, payload: ApplicationTransition) -> ApplicationDetail:
    """验证合法状态、材料和确认；投递锁定与状态事件原子提交，后续永不解锁。"""
    entity = await _locked_application(session, application_id)
    before = entity.current_status
    if payload.status not in TRANSITIONS[before]:
        raise ConflictError("当前阶段不允许此状态变更。")
    if payload.status == S.APPLIED and not payload.confirm_applied:
        raise ValidationFailedError("请确认已在外部平台完成投递。")
    if payload.status in (S.READY_TO_APPLY, S.APPLIED) and entity.resume_version_id is None:
        raise ValidationFailedError("就绪或记录投递前必须选择实际使用的正式简历版本。")
    if payload.status in (S.PREPARING, S.READY_TO_APPLY):
        exclusion = await current_exclusion(session, entity.job_opportunity_id, entity.job_snapshot_id)
        if not exclusion.preparation_allowed:
            raise ConflictError("当前排除策略要求先核对或登记本职位例外，不能进入投递准备。")
    updates: dict[str, Any] = {"current_status": payload.status}
    if payload.status == S.APPLIED:
        updates["material_locked_at"] = datetime.now(UTC)
    await apply_versioned_update(session, entity, payload.version, updates)
    event_payload = (
        {"inputs": _inputs(entity).model_dump(mode="json"), "confirm_applied": True}
        if payload.status == S.APPLIED
        else {}
    )
    await _append_event(
        session,
        entity,
        "APPLIED" if payload.status == S.APPLIED else "STATUS_CHANGED",
        before,
        event_payload,
        payload.notes,
    )
    await session.commit()
    return await detail(session, entity.id)
