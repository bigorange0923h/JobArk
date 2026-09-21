"""Resume 领域的数据访问层。

只负责读写与查询构造，不做业务判断：状态机、乐观锁、引用完整性都在 `service.py`。
事务由服务层控制，本层不调用 `commit`。

本模块直接查询 Profile 领域的两张表（`profile_revisions`、`profile_evidences`）：
简历版本必须可溯源到资料修订与证据，这个依赖是领域事实而非实现细节，
因此显式使用 Profile 的模型，而不是绕过外键另建一套读取。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.modules.profile.models import ProfileEvidence, ProfileRevision

from .enums import DraftStatus, ResumeStatus
from .models import Resume, ResumeDraft, ResumeVersion, ResumeVersionEvidence


async def get_by_id[ModelT: Base](
    session: AsyncSession,
    model: type[ModelT],
    entity_id: uuid.UUID,
) -> ModelT | None:
    """按主键读取实体。

    参数:
        session: 当前会话。
        model: 目标模型类。
        entity_id: 主键。

    返回:
        ModelT | None: 实体实例；不存在时为 None。
    """
    return await session.get(model, entity_id)


async def list_resumes(session: AsyncSession, *, include_archived: bool) -> Sequence[Resume]:
    """列出简历方向。

    参数:
        session: 当前会话。
        include_archived: 是否包含已归档的简历方向。

    返回:
        Sequence[Resume]: 按创建时间升序排列的简历方向。
    """
    statement = select(Resume)
    if not include_archived:
        statement = statement.where(Resume.status != ResumeStatus.ARCHIVED)
    return (await session.scalars(statement.order_by(Resume.created_at))).all()


async def list_versions(session: AsyncSession, resume_id: uuid.UUID, *, limit: int) -> Sequence[ResumeVersion]:
    """列出某份简历的版本，最新在前。

    参数:
        session: 当前会话。
        resume_id: 所属简历。
        limit: 返回条数上限。

    返回:
        Sequence[ResumeVersion]: 版本列表，按版本号倒序。
    """
    statement = (
        select(ResumeVersion)
        .where(ResumeVersion.resume_id == resume_id)
        .order_by(ResumeVersion.version_no.desc())
        .limit(limit)
    )
    return (await session.scalars(statement)).all()


async def next_version_no(session: AsyncSession, resume_id: uuid.UUID) -> int:
    """计算下一个版本号。

    参数:
        session: 当前会话。
        resume_id: 所属简历。

    返回:
        int: 下一个版本号，从 1 开始。

    注意:
        这里只做"当前最大值 + 1"；并发下可能算出同一个号，由
        `UNIQUE(resume_id, version_no)` 兜底，服务层把它转成可理解的冲突错误。
    """
    current = await session.scalar(
        select(func.max(ResumeVersion.version_no)).where(ResumeVersion.resume_id == resume_id)
    )
    return (current or 0) + 1


async def list_version_ids_with_evidences(
    session: AsyncSession,
    version_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """批量读取版本关联的证据主键。

    参数:
        session: 当前会话。
        version_ids: 版本主键列表。

    返回:
        dict[uuid.UUID, list[uuid.UUID]]: 版本主键到证据主键列表的映射；无关联的版本不出现在结果中。

    注意:
        一次性查询而不是逐个版本查询：列表接口若按版本逐条查询会产生 N+1 次往返。
    """
    if not version_ids:
        return {}
    statement = (
        select(ResumeVersionEvidence.resume_version_id, ResumeVersionEvidence.evidence_id)
        .where(ResumeVersionEvidence.resume_version_id.in_(version_ids))
        .order_by(ResumeVersionEvidence.created_at)
    )
    grouped: dict[uuid.UUID, list[uuid.UUID]] = {}
    for version_id, evidence_id in (await session.execute(statement)).all():
        grouped.setdefault(version_id, []).append(evidence_id)
    return grouped


async def list_drafts(
    session: AsyncSession,
    resume_id: uuid.UUID,
    *,
    status: DraftStatus | None = None,
    limit: int,
) -> Sequence[ResumeDraft]:
    """列出候选稿，最新在前。

    参数:
        session: 当前会话。
        resume_id: 所属简历。
        status: 只返回该状态的候选稿；为 None 时返回全部。
        limit: 返回条数上限。

    返回:
        Sequence[ResumeDraft]: 候选稿列表。
    """
    statement = select(ResumeDraft).where(ResumeDraft.resume_id == resume_id)
    if status is not None:
        statement = statement.where(ResumeDraft.status == status)
    statement = statement.order_by(ResumeDraft.created_at.desc()).limit(limit)
    return (await session.scalars(statement)).all()


async def get_profile_revision(session: AsyncSession, revision_id: uuid.UUID) -> ProfileRevision | None:
    """读取资料修订。

    参数:
        session: 当前会话。
        revision_id: 修订主键。

    返回:
        ProfileRevision | None: 修订实例；不存在时为 None。
    """
    return await session.get(ProfileRevision, revision_id)


async def list_evidences_by_ids(
    session: AsyncSession,
    evidence_ids: Sequence[uuid.UUID],
) -> Sequence[ProfileEvidence]:
    """按主键批量读取证据。

    参数:
        session: 当前会话。
        evidence_ids: 证据主键列表。

    返回:
        Sequence[ProfileEvidence]: 找到的证据；不存在的不会出现在结果中，
        由调用方通过数量差异判断并给出字段级错误。
    """
    if not evidence_ids:
        return []
    return (await session.scalars(select(ProfileEvidence).where(ProfileEvidence.id.in_(evidence_ids)))).all()


async def add[ModelT: Base](session: AsyncSession, entity: ModelT) -> ModelT:
    """把实体加入会话并落库到当前事务。

    参数:
        session: 当前会话。
        entity: 待新增实体。

    返回:
        ModelT: 已 flush 的实体；数据库侧默认值已回填。

    注意:
        只 flush 不 commit：提交由服务层决定，避免把多个写操作拆成多个事务。
    """
    session.add(entity)
    await session.flush()
    return entity


async def add_version_evidences(
    session: AsyncSession,
    version_id: uuid.UUID,
    evidence_ids: Sequence[uuid.UUID],
) -> None:
    """写入版本与证据的关联。

    参数:
        session: 当前会话。
        version_id: 版本主键。
        evidence_ids: 去重后的证据主键。
    """
    if not evidence_ids:
        return
    session.add_all(
        ResumeVersionEvidence(resume_version_id=version_id, evidence_id=evidence_id) for evidence_id in evidence_ids
    )
    await session.flush()
