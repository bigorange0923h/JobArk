"""Profile 领域的数据访问层。

只负责读写与查询构造，不做业务判断：唯一性、乐观锁、引用完整性检查等规则都在 `service.py`。
事务由服务层控制，本层不调用 `commit`。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base

from ..matching.models import MatchResult
from ..resume.models import ResumeDraft, ResumeVersion, ResumeVersionEvidence
from .models import (
    PersonalProfile,
    ProfileEducation,
    ProfileEvidence,
    ProfileExperience,
    ProfileLanguage,
    ProfilePreference,
    ProfileProject,
    ProfileRevision,
    ProfileSkill,
)

PROFILE_SINGLETON_KEY = "default"
"""V1 单人档案的固定键；唯一约束保证不会出现第二份主档案。"""


async def get_profile(session: AsyncSession) -> PersonalProfile | None:
    """读取单例档案。

    参数:
        session: 当前会话。

    返回:
        PersonalProfile | None: 档案实例；尚未创建时为 None。

    注意:
        子项关系配置为 `lazy="selectin"`，因此事实与证据会随档案一并加载，
        避免在异步上下文里触发惰性加载（会抛 MissingGreenlet）。
    """
    return await session.scalar(select(PersonalProfile).where(PersonalProfile.singleton_key == PROFILE_SINGLETON_KEY))


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


async def list_evidences(
    session: AsyncSession, profile_id: uuid.UUID, *, include_archived: bool
) -> Sequence[ProfileEvidence]:
    """列出证据。

    参数:
        session: 当前会话。
        profile_id: 所属档案。
        include_archived: 是否包含已归档证据。

    返回:
        Sequence[ProfileEvidence]: 按创建时间升序排列的证据。
    """
    statement = select(ProfileEvidence).where(ProfileEvidence.profile_id == profile_id)
    if not include_archived:
        statement = statement.where(ProfileEvidence.archived_at.is_(None))
    return (await session.scalars(statement.order_by(ProfileEvidence.created_at))).all()


async def get_preference(session: AsyncSession, profile_id: uuid.UUID) -> ProfilePreference | None:
    """读取档案的求职偏好。

    参数:
        session: 当前会话。
        profile_id: 所属档案。

    返回:
        ProfilePreference | None: 偏好实例；未设置时为 None。
    """
    return await session.scalar(select(ProfilePreference).where(ProfilePreference.profile_id == profile_id))


async def skill_name_exists(
    session: AsyncSession,
    profile_id: uuid.UUID,
    name_normalized: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """判断同一档案内是否已存在同名规范化技能。

    参数:
        session: 当前会话。
        profile_id: 所属档案。
        name_normalized: 规范化后的技能名。
        exclude_id: 需要排除的记录（更新自身时使用）。

    返回:
        bool: 已存在返回 True。
    """
    statement = (
        select(func.count())
        .select_from(ProfileSkill)
        .where(
            ProfileSkill.profile_id == profile_id,
            ProfileSkill.name_normalized == name_normalized,
            ProfileSkill.archived_at.is_(None),
        )
    )
    if exclude_id is not None:
        statement = statement.where(ProfileSkill.id != exclude_id)
    return bool(await session.scalar(statement))


async def count_external_references(session: AsyncSession, profile_id: uuid.UUID) -> dict[str, int]:
    """统计其他领域对当前档案数据的引用数量。

    参数:
        session: 当前会话。
        profile_id: 所属档案。

    返回:
        dict[str, int]: 引用方名称到引用条数的映射，只包含数量大于 0 的引用方。

    注意:
        读取 resume/matching 的模型是刻意的跨域只读检查：这两域指向
        profile_revisions / profile_evidences 的外键均为 RESTRICT，
        重置档案前必须先确认没有引用，否则删除会以 IntegrityError 变成 500。
        本函数不修改任何 resume/matching 数据，事务边界仍由 profile 服务层控制。
    """
    revision_ids = select(ProfileRevision.id).where(ProfileRevision.profile_id == profile_id)
    evidence_ids = select(ProfileEvidence.id).where(ProfileEvidence.profile_id == profile_id)
    checks = {
        "简历候选稿": select(func.count())
        .select_from(ResumeDraft)
        .where(ResumeDraft.source_profile_revision_id.in_(revision_ids)),
        "简历版本": select(func.count())
        .select_from(ResumeVersion)
        .where(ResumeVersion.profile_revision_id.in_(revision_ids)),
        "简历版本证据关联": select(func.count())
        .select_from(ResumeVersionEvidence)
        .where(ResumeVersionEvidence.evidence_id.in_(evidence_ids)),
        "匹配结果": select(func.count())
        .select_from(MatchResult)
        .where(MatchResult.profile_revision_id.in_(revision_ids)),
    }

    counts: dict[str, int] = {}
    for name, statement in checks.items():
        count = int(await session.scalar(statement) or 0)
        if count > 0:
            counts[name] = count
    return counts


async def delete_profile_data(session: AsyncSession, profile_id: uuid.UUID) -> None:
    """按外键依赖顺序物理删除档案及全部子表数据。

    参数:
        session: 当前会话。
        profile_id: 所属档案。

    注意:
        删除顺序必须满足 RESTRICT 外键：先删修订与各类事实（它们可能引用证据），
        再删偏好与证据，最后删档案根。本函数不做跨域引用检查、不提交事务：
        前者由服务层在调用前完成，后者由服务层在全部删除成功后一次性提交，
        保证重置要么完整生效、要么整体回滚。
    """
    await session.execute(delete(ProfileRevision).where(ProfileRevision.profile_id == profile_id))
    for model in (ProfileSkill, ProfileExperience, ProfileProject, ProfileEducation, ProfileLanguage):
        await session.execute(delete(model).where(model.profile_id == profile_id))
    await session.execute(delete(ProfilePreference).where(ProfilePreference.profile_id == profile_id))
    await session.execute(delete(ProfileEvidence).where(ProfileEvidence.profile_id == profile_id))
    await session.execute(delete(PersonalProfile).where(PersonalProfile.id == profile_id))


async def add[ModelT: Base](session: AsyncSession, entity: ModelT) -> ModelT:
    """把实体加入会话并落库到当前事务。

    参数:
        session: 当前会话。
        entity: 待新增实体。

    返回:
        ModelT: 已 flush 的实体；数据库侧默认值（创建时间等）已回填。

    注意:
        只 flush 不 commit：提交由服务层决定，避免把多个写操作拆成多个事务。
    """
    session.add(entity)
    await session.flush()
    return entity


async def remove(session: AsyncSession, entity: Base) -> None:
    """删除实体。

    参数:
        session: 当前会话。
        entity: 待删除实体。
    """
    await session.delete(entity)
    await session.flush()


async def list_revisions(session: AsyncSession, profile_id: uuid.UUID, *, limit: int) -> Sequence[ProfileRevision]:
    """列出资料修订，最新在前。

    参数:
        session: 当前会话。
        profile_id: 所属档案。
        limit: 返回条数上限。

    返回:
        Sequence[ProfileRevision]: 修订列表。
    """
    statement = (
        select(ProfileRevision)
        .where(ProfileRevision.profile_id == profile_id)
        .order_by(ProfileRevision.revision_no.desc())
        .limit(limit)
    )
    return (await session.scalars(statement)).all()


async def next_revision_no(session: AsyncSession, profile_id: uuid.UUID) -> int:
    """计算下一个修订号。

    参数:
        session: 当前会话。
        profile_id: 所属档案。

    返回:
        int: 下一个修订号，从 1 开始。
    """
    await session.scalar(select(PersonalProfile).where(PersonalProfile.id == profile_id).with_for_update())
    current = await session.scalar(
        select(func.max(ProfileRevision.revision_no)).where(ProfileRevision.profile_id == profile_id)
    )
    return (current or 0) + 1


async def find_projects_by_experience(
    session: AsyncSession,
    experience_id: uuid.UUID,
) -> Sequence[ProfileProject]:
    """查找关联到某段工作经历的项目。

    参数:
        session: 当前会话。
        experience_id: 工作经历主键。

    返回:
        Sequence[ProfileProject]: 关联到该经历的项目；删除经历前用它给出可理解的 409 而不是外键报错。
    """
    result = await session.scalars(select(ProfileProject).where(ProfileProject.experience_id == experience_id))
    return result.all()


async def find_revisions_referencing(
    session: AsyncSession,
    snapshot_key: str,
    fact_id: uuid.UUID,
) -> Sequence[int]:
    """查找引用了某条事实的修订号。

    参数:
        session: 当前会话。
        snapshot_key: 快照中的字段名，例如 `skills`。
        fact_id: 事实记录主键。

    返回:
        Sequence[int]: 引用该事实的修订号列表。

    注意:
        用 JSONB 包含查询（`@>`）而不是逐行扫描：快照结构由服务层固定为
        `{<snapshot_key>: [{"id": "..."}, ...]}`，因此可以用索引化的包含判断。
    """
    statement = select(ProfileRevision.revision_no).where(
        ProfileRevision.snapshot_json[snapshot_key].contains([{"id": str(fact_id)}])
    )
    return (await session.scalars(statement.order_by(ProfileRevision.revision_no))).all()
