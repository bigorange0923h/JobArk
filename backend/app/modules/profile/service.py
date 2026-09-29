"""Profile 领域的业务规则。

职责边界：

- 规则判断集中在此：唯一性、乐观锁、引用完整性、数据真实性；路由只做参数绑定与响应包装。
- 事务由本层显式提交（会话依赖不做隐式提交），每个写操作一个事务。
- 纯计算（技能名规范化、修订快照构造）保持同步函数：ADR 0002 明确"为了统一而到处加 async"
  会在事件循环里同步阻塞且更难测试。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.errors import ConflictError, ResourceNotFoundError, ValidationFailedError
from app.core.responses import ErrorDetail
from app.core.versioning import apply_versioned_update, collect_updates

from . import repository as repo
from .enums import ClaimStatus, EvidenceSourceType, VerificationStatus
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
from .schemas import (
    EducationCreate,
    EducationUpdate,
    EvidenceCreate,
    EvidenceUpdate,
    ExperienceCreate,
    ExperienceUpdate,
    LanguageCreate,
    LanguageUpdate,
    PreferenceUpsert,
    ProfileCreate,
    ProfileLink,
    ProfileUpdate,
    ProjectCreate,
    ProjectUpdate,
    RevisionCreate,
    SkillCreate,
    SkillUpdate,
)

# 事实模型与修订快照字段名的对应关系；删除前用它判断该事实是否已被修订引用。
SNAPSHOT_KEY_BY_MODEL: dict[type[Base], str] = {
    ProfileSkill: "skills",
    ProfileExperience: "experiences",
    ProfileProject: "projects",
    ProfileEducation: "educations",
    ProfileLanguage: "languages",
}

# 「本人编辑」证据的固定标题：同一档案只保留一条，避免每轮编辑都新增一行证据。
MANUAL_EDIT_EVIDENCE_TITLE = "本人编辑：内容修订"

# 各事实的"内容字段"：这些字段一变，事实内容就变了，来源必须重新归因（见 `_reattribute_edited_fact`）。
CONTENT_FIELDS_BY_MODEL: dict[type[Base], tuple[str, ...]] = {
    ProfileSkill: ("name", "category", "proficiency", "years_of_experience"),
    ProfileExperience: (
        "company",
        "title",
        "location",
        "start_date",
        "end_date",
        "responsibilities",
        "achievements",
    ),
    ProfileProject: ("name", "role", "description", "achievements", "tech_stack", "url", "start_date", "end_date"),
    ProfileEducation: ("school", "major", "degree", "start_date", "end_date"),
    ProfileLanguage: ("language", "level", "note"),
}


def normalize_skill_name(name: str) -> str:
    """规范化技能名。

    参数:
        name: 用户书写的技能名。

    返回:
        str: 折叠连续空白并转为小写后的名称，用于同一档案内的唯一性判断。

    注意:
        这是纯计算，保持同步函数；调用方在异步上下文中直接调用即可。
    """
    return " ".join(name.split()).lower()


def build_profile_snapshot(profile: PersonalProfile) -> dict[str, Any]:
    """构造资料修订快照。

    参数:
        profile: 当前档案（含已加载的事实与证据）。

    返回:
        dict[str, Any]: 可直接写入 `profile_revisions.snapshot_json` 的结构。

    注意:
        刻意不包含 `email` 与 `phone`：联系方式与匹配、简历生成无关，而快照会被后续 LLM 流程读取，
        不写入快照可以从源头上避免联系方式被带进提示词。
    """
    return {
        "profile": {
            "id": str(profile.id),
            "full_name": profile.full_name,
            "headline": profile.headline,
            "summary": profile.summary,
            "city": profile.city,
            "links": profile.links,
        },
        "evidences": [
            {
                "id": str(evidence.id),
                "source_type": evidence.source_type.value,
                "title": evidence.title,
                "source_url": evidence.source_url,
                "verification_status": evidence.verification_status.value,
            }
            for evidence in profile.evidences
            if evidence.archived_at is None
        ],
        "skills": [
            {
                "id": str(skill.id),
                "name": skill.name,
                "category": skill.category,
                "proficiency": skill.proficiency.value if skill.proficiency else None,
                "years_of_experience": float(skill.years_of_experience) if skill.years_of_experience else None,
                "source_evidence_id": str(skill.source_evidence_id) if skill.source_evidence_id else None,
                "claim_status": skill.claim_status.value,
            }
            for skill in profile.skills
        ],
        "experiences": [
            {
                "id": str(item.id),
                "company": item.company,
                "title": item.title,
                "location": item.location,
                "start_date": item.start_date.isoformat(),
                "end_date": item.end_date.isoformat() if item.end_date else None,
                "responsibilities": item.responsibilities,
                "achievements": item.achievements,
                "source_evidence_id": str(item.source_evidence_id) if item.source_evidence_id else None,
            }
            for item in profile.experiences
        ],
        "projects": [
            {
                "id": str(item.id),
                "name": item.name,
                "role": item.role,
                "description": item.description,
                "achievements": item.achievements,
                "tech_stack": item.tech_stack,
                "url": item.url,
                "source_evidence_id": str(item.source_evidence_id) if item.source_evidence_id else None,
            }
            for item in profile.projects
        ],
        "educations": [
            {
                "id": str(item.id),
                "school": item.school,
                "major": item.major,
                "degree": item.degree,
                "source_evidence_id": str(item.source_evidence_id) if item.source_evidence_id else None,
            }
            for item in profile.educations
        ],
        "languages": [
            {
                "id": str(item.id),
                "language": item.language,
                "level": item.level,
                "source_evidence_id": str(item.source_evidence_id) if item.source_evidence_id else None,
            }
            for item in profile.languages
        ],
    }


def _ensure_owned(entity_profile_id: uuid.UUID, profile_id: uuid.UUID) -> None:
    """校验记录属于当前档案。

    参数:
        entity_profile_id: 记录所属档案。
        profile_id: 当前档案。

    异常:
        ResourceNotFoundError: 不属于当前档案时按"不存在"处理，避免泄露其他档案的存在性。
    """
    if entity_profile_id != profile_id:
        raise ResourceNotFoundError("请求的资源不存在。")


async def _require_fact[FactT: Base](session: AsyncSession, model: type[FactT], fact_id: uuid.UUID) -> FactT:
    """读取事实记录，不存在则 404。

    参数:
        session: 当前会话。
        model: 事实模型类。
        fact_id: 记录主键。

    返回:
        ModelT: 事实记录。

    异常:
        ResourceNotFoundError: 记录不存在时抛出。
    """
    entity = await repo.get_by_id(session, model, fact_id)
    if entity is None:
        raise ResourceNotFoundError("请求的资源不存在。")
    return entity


async def _ensure_evidence_usable(session: AsyncSession, evidence_id: uuid.UUID | None) -> None:
    """校验被引用的证据存在且未归档。

    参数:
        session: 当前会话。
        evidence_id: 证据主键；为 None 时直接通过。

    异常:
        ValidationFailedError: 证据不存在或已归档时抛出 422，并指出出错字段。
    """
    if evidence_id is None:
        return
    evidence = await repo.get_by_id(session, ProfileEvidence, evidence_id)
    if evidence is None or evidence.archived_at is not None:
        raise ValidationFailedError(
            "引用的证据不存在或已归档。",
            details=[ErrorDetail(field="source_evidence_id", reason="证据不存在或已归档，请先补录或改用其他证据。")],
        )


async def _manual_edit_evidence(session: AsyncSession, profile_id: uuid.UUID) -> uuid.UUID:
    """返回「本人编辑」证据的主键；不存在时创建。

    参数:
        session: 当前会话。
        profile_id: 档案主键。

    返回:
        uuid.UUID: 可用于重新归因的证据主键。

    注意:
        同一档案只保留一条（标题固定），因此多轮编辑不会堆积大量证据行。它属于
        `MANUAL_DECLARATION`（本人陈述），与简历文档证据有明确区别。
    """
    existing = await session.scalar(
        select(ProfileEvidence).where(
            ProfileEvidence.profile_id == profile_id,
            ProfileEvidence.source_type == EvidenceSourceType.MANUAL_DECLARATION,
            ProfileEvidence.title == MANUAL_EDIT_EVIDENCE_TITLE,
            ProfileEvidence.archived_at.is_(None),
        )
    )
    if existing is not None:
        return existing.id
    evidence = ProfileEvidence(
        profile_id=profile_id,
        source_type=EvidenceSourceType.MANUAL_DECLARATION,
        title=MANUAL_EDIT_EVIDENCE_TITLE,
        content="用户在档案页直接修改的内容（来源为本人陈述，不是简历原文）。",
        verification_status=VerificationStatus.UNVERIFIED,
    )
    session.add(evidence)
    await session.flush()
    return evidence.id


async def _reattribute_edited_fact(
    session: AsyncSession,
    fact: ProfileSkill | ProfileExperience | ProfileProject | ProfileEducation | ProfileLanguage,
    updates: dict[str, Any],
) -> None:
    """事实内容被修改后，把它从简历文档证据改挂到「本人填写」证据。

    参数:
        session: 当前会话。
        fact: 被更新的记录（用于读取当前来源与所属档案）。
        updates: 本次实际更新的字段；需要重新归因时会被就地写入 `source_evidence_id`。

    返回:
        None

    注意:
        只有三件事同时成立才重新归因：内容字段确实变了、当前来源是简历文档证据、用户没有在本次
        请求里显式指定来源。否则编辑后的内容会继续挂在旧简历摘录下，等于让旧摘录为新内容背书——
        那正是"结论可追溯到证据"要禁止的事。历史证据记录不删除，只是不再被这条事实引用；
        不存在"必须补交证明"的要求：归因由系统自动完成。
    """
    if "source_evidence_id" in updates:
        return
    if not any(field in updates for field in CONTENT_FIELDS_BY_MODEL[type(fact)]):
        return
    if fact.source_evidence_id is None:
        # 本来就没有来源（本人填写或手工录入），没有需要修正的归因。
        return
    current = await session.get(ProfileEvidence, fact.source_evidence_id)
    if current is None or current.source_type is not EvidenceSourceType.RESUME_DOCUMENT:
        return
    updates["source_evidence_id"] = await _manual_edit_evidence(session, fact.profile_id)


async def _ensure_experience_usable(
    session: AsyncSession,
    profile_id: uuid.UUID,
    experience_id: uuid.UUID | None,
) -> None:
    """校验被关联的工作经历存在且属于当前档案。

    参数:
        session: 当前会话。
        profile_id: 当前档案主键。
        experience_id: 工作经历主键；为 None 时直接通过。

    异常:
        ValidationFailedError: 经历不存在或不属于本档案时抛出 422，并指出出错字段。

    注意:
        外键只保证"记录存在"，不保证"属于同一份档案"。显式校验让这种情况得到可理解的
        字段级 422，而不是等数据库抛完整性错误变成 500。
    """
    if experience_id is None:
        return
    experience = await repo.get_by_id(session, ProfileExperience, experience_id)
    if experience is None or experience.profile_id != profile_id:
        raise ValidationFailedError(
            "关联的工作经历不存在。",
            details=[ErrorDetail(field="experience_id", reason="请选择本档案中已有的工作经历。")],
        )


async def _ensure_experience_unlinked(session: AsyncSession, experience: ProfileExperience) -> None:
    """校验工作经历没有被任何项目关联。

    参数:
        session: 当前会话。
        experience: 待删除的工作经历。

    异常:
        ConflictError: 仍被项目关联时抛出 409，并列出项目名。

    注意:
        关联是用户建立的关系，直接删掉经历会让那些项目静默失去归属；这里明确阻止，
        与"被资料修订引用不可删除"是同一条原则：宁可让用户多做一步，也不静默丢信息。
    """
    linked = await repo.find_projects_by_experience(session, experience.id)
    if not linked:
        return
    names = "、".join(project.name for project in linked)
    raise ConflictError(
        "该工作经历已被项目经历关联，不能删除。",
        details=[ErrorDetail(field=None, reason=f"关联的项目：{names}。请先取消关联或删除这些项目。")],
    )


async def _ensure_fact_not_referenced(session: AsyncSession, model: type[Base], fact_id: uuid.UUID) -> None:
    """校验事实未被任何资料修订引用。

    参数:
        session: 当前会话。
        model: 事实模型类。
        fact_id: 记录主键。

    异常:
        ConflictError: 已被修订引用时抛出 409，并列出引用它的修订号。

    注意:
        修订是不可变历史；允许删除被引用的事实会让历史修订指向不存在的记录，
        "匹配与简历可复现"的前提随之失效。
    """
    revision_numbers = await repo.find_revisions_referencing(session, SNAPSHOT_KEY_BY_MODEL[model], fact_id)
    if revision_numbers:
        referenced_by = ", ".join(str(number) for number in revision_numbers)
        raise ConflictError(
            "该记录已被资料修订引用，不能删除。",
            details=[ErrorDetail(field=None, reason=f"被修订 {referenced_by} 引用；请先处理相关修订。")],
        )


# --------------------------------------------------------------------------------------------
# 档案根
# --------------------------------------------------------------------------------------------


async def _reload_profile(session: AsyncSession) -> PersonalProfile:
    """重新查询档案聚合，确保子项已随查询加载。

    参数:
        session: 当前会话。

    返回:
        PersonalProfile: 子项已加载的档案。

    异常:
        ResourceNotFoundError: 档案不存在（正常流程中不会发生）。

    注意:
        写入后必须重新查询，不能直接返回刚 flush 的实例：那些实例的集合关系尚未加载，
        而 Pydantic 在同步上下文序列化时会触发惰性加载，在异步会话下直接抛 MissingGreenlet。
        `lazy="selectin"` 只在"由查询加载"时生效，这是它的关键前提。
    """
    profile = await repo.get_profile(session)
    if profile is None:
        raise ResourceNotFoundError("个人档案尚未创建。")
    return profile


async def require_profile(session: AsyncSession) -> PersonalProfile:
    """读取当前档案，不存在则 404。

    参数:
        session: 当前会话。

    返回:
        PersonalProfile: 档案聚合（含子项）。

    异常:
        ResourceNotFoundError: 尚未创建档案时抛出，调用方据此返回 404。
    """
    profile = await repo.get_profile(session)
    if profile is None:
        raise ResourceNotFoundError("个人档案尚未创建。")
    return profile


async def create_profile(session: AsyncSession, payload: ProfileCreate) -> PersonalProfile:
    """创建单例档案。

    参数:
        session: 当前会话。
        payload: 创建请求体。

    返回:
        PersonalProfile: 新档案。

    异常:
        ConflictError: 档案已存在时抛出 409；V1 只允许一份主档案。
    """
    if await repo.get_profile(session) is not None:
        raise ConflictError("个人档案已存在，请直接更新。")
    profile = PersonalProfile(
        full_name=payload.full_name,
        headline=payload.headline,
        summary=payload.summary,
        email=payload.email,
        phone=payload.phone,
        city=payload.city,
        links=[link.model_dump() for link in payload.links],
    )
    await repo.add(session, profile)
    await session.commit()
    return await _reload_profile(session)


async def update_profile(session: AsyncSession, payload: ProfileUpdate) -> PersonalProfile:
    """局部更新档案根信息。

    参数:
        session: 当前会话。
        payload: 局部更新请求体。

    返回:
        PersonalProfile: 更新后的档案。

    异常:
        ResourceNotFoundError: 档案尚未创建。
        ConflictError: 版本号不匹配。
    """
    profile = await require_profile(session)
    updates = collect_updates(payload)
    if "links" in updates:
        updates["links"] = [ProfileLink.model_validate(item).model_dump() for item in updates["links"]]
    await apply_versioned_update(session, profile, payload.version, updates)
    await session.commit()
    return await _reload_profile(session)


async def reset_profile(session: AsyncSession) -> uuid.UUID:
    """重置个人档案：物理删除档案根与全部子表数据，回到未创建状态。

    参数:
        session: 当前会话。

    返回:
        uuid.UUID: 被删除档案的主键。

    异常:
        ResourceNotFoundError: 档案尚未创建。
        ConflictError: 简历版本或匹配结果仍引用档案的修订/证据。

    注意:
        仅供本地维护使用的破坏性操作，不在前端暴露。与单条删除不同，
        这里连不可变修订也一并删除——这是用户明确选择的重置语义；
        但其他领域（简历版本、匹配结果）已经引用修订或证据时仍拒绝执行，
        否则那些历史记录会指向不存在的档案数据。
    """
    profile = await require_profile(session)
    # 先取出主键：提交后会话默认过期实例属性，异步上下文下再访问会触发惰性加载。
    profile_id = profile.id

    external = await repo.count_external_references(session, profile_id)
    if external:
        referenced = "；".join(f"{name} {count} 条" for name, count in external.items())
        raise ConflictError(
            "存在引用档案数据的简历版本或匹配结果，无法重置。",
            details=[ErrorDetail(field=None, reason=f"请先删除相关记录后再重置：{referenced}。")],
        )

    await repo.delete_profile_data(session, profile_id)
    await session.commit()
    return profile_id


# --------------------------------------------------------------------------------------------
# 证据
# --------------------------------------------------------------------------------------------


async def list_evidences(session: AsyncSession, *, include_archived: bool) -> Sequence[ProfileEvidence]:
    """列出当前档案的证据。

    参数:
        session: 当前会话。
        include_archived: 是否包含已归档证据。

    返回:
        Sequence[ProfileEvidence]: 证据列表。
    """
    profile = await require_profile(session)
    return await repo.list_evidences(session, profile.id, include_archived=include_archived)


async def create_evidence(session: AsyncSession, payload: EvidenceCreate) -> ProfileEvidence:
    """新增证据。

    参数:
        session: 当前会话。
        payload: 创建请求体。

    返回:
        ProfileEvidence: 新证据。
    """
    profile = await require_profile(session)
    evidence = ProfileEvidence(
        profile_id=profile.id,
        source_type=payload.source_type,
        title=payload.title,
        content=payload.content,
        source_url=payload.source_url,
        source_hash=payload.source_hash,
        verification_status=payload.verification_status,
    )
    await repo.add(session, evidence)
    await session.commit()
    return evidence


async def update_evidence(session: AsyncSession, evidence_id: uuid.UUID, payload: EvidenceUpdate) -> ProfileEvidence:
    """局部更新证据。

    参数:
        session: 当前会话。
        evidence_id: 证据主键。
        payload: 局部更新请求体。

    返回:
        ProfileEvidence: 更新后的证据。

    异常:
        ResourceNotFoundError: 证据不存在。
        ConflictError: 版本号不匹配。
    """
    profile = await require_profile(session)
    evidence = await _require_fact(session, ProfileEvidence, evidence_id)
    _ensure_owned(evidence.profile_id, profile.id)
    await apply_versioned_update(session, evidence, payload.version, collect_updates(payload))
    await session.commit()
    return evidence


async def archive_evidence(session: AsyncSession, evidence_id: uuid.UUID) -> ProfileEvidence:
    """归档证据。

    参数:
        session: 当前会话。
        evidence_id: 证据主键。

    返回:
        ProfileEvidence: 归档后的证据。

    注意:
        界面的"删除"在此实现为归档：证据可能被多条事实引用，物理删除会让这些引用的目标消失，
        使"结论可追溯到证据"失效。归档后该证据不再出现在默认列表与修订快照中。
    """
    profile = await require_profile(session)
    evidence = await _require_fact(session, ProfileEvidence, evidence_id)
    _ensure_owned(evidence.profile_id, profile.id)
    evidence.archived_at = datetime.now(UTC)
    evidence.version += 1
    await session.flush()
    # `updated_at` 由数据库端 `onupdate=now()` 生成，flush 后该属性处于过期状态；
    # 不显式刷新就交给 Pydantic 序列化，会在同步上下文触发惰性加载并抛 MissingGreenlet。
    await session.refresh(evidence)
    await session.commit()
    return evidence


# --------------------------------------------------------------------------------------------
# 技能
# --------------------------------------------------------------------------------------------


async def _ensure_skill_name_available(
    session: AsyncSession,
    profile_id: uuid.UUID,
    name_normalized: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """校验同一档案内技能名不重复。

    参数:
        session: 当前会话。
        profile_id: 所属档案。
        name_normalized: 规范化技能名。
        exclude_id: 更新自身时需要排除的记录。

    异常:
        ConflictError: 已存在同名技能时抛出 409。

    注意:
        数据库也有唯一约束兜底；这里提前判断是为了返回可理解的错误与字段位置，
        而不是把 IntegrityError 变成 500。
    """
    if await repo.skill_name_exists(session, profile_id, name_normalized, exclude_id=exclude_id):
        raise ConflictError(
            "该技能已存在。",
            details=[ErrorDetail(field="name", reason=f"规范化名称 {name_normalized} 已被占用。")],
        )


def _ensure_claim_supported(claim_status: ClaimStatus, source_evidence_id: uuid.UUID | None) -> None:
    """校验"已验证"技能必须挂证据。

    参数:
        claim_status: 目标验证状态。
        source_evidence_id: 目标证据。

    异常:
        ValidationFailedError: 缺少证据却标记为 VERIFIED 时抛出 422。

    注意:
        数据库有同样的 CHECK 约束；应用层重复校验是为了给出 422 与字段级原因，
        而不是让用户看到一个没有解释的 500。
    """
    if claim_status is ClaimStatus.VERIFIED and source_evidence_id is None:
        raise ValidationFailedError(
            "标记为已验证的技能必须关联证据。",
            details=[ErrorDetail(field="source_evidence_id", reason="缺少证据，无法标记为 VERIFIED。")],
        )


async def create_skill(session: AsyncSession, payload: SkillCreate) -> ProfileSkill:
    """新增技能。

    参数:
        session: 当前会话。
        payload: 创建请求体。

    返回:
        ProfileSkill: 新技能。
    """
    profile = await require_profile(session)
    normalized = normalize_skill_name(payload.name)
    await _ensure_skill_name_available(session, profile.id, normalized)
    await _ensure_evidence_usable(session, payload.source_evidence_id)
    _ensure_claim_supported(payload.claim_status, payload.source_evidence_id)

    skill = ProfileSkill(
        profile_id=profile.id,
        name=payload.name,
        name_normalized=normalized,
        category=payload.category,
        proficiency=payload.proficiency,
        years_of_experience=payload.years_of_experience,
        source_evidence_id=payload.source_evidence_id,
        claim_status=payload.claim_status,
        sort_order=payload.sort_order,
    )
    await repo.add(session, skill)
    await session.commit()
    return skill


async def update_skill(session: AsyncSession, skill_id: uuid.UUID, payload: SkillUpdate) -> ProfileSkill:
    """局部更新技能。

    参数:
        session: 当前会话。
        skill_id: 技能主键。
        payload: 局部更新请求体。

    返回:
        ProfileSkill: 更新后的技能。

    异常:
        ResourceNotFoundError: 技能不存在。
        ConflictError: 版本号不匹配或名称重复。
        ValidationFailedError: 变更后状态与证据不匹配。
    """
    profile = await require_profile(session)
    skill = await _require_fact(session, ProfileSkill, skill_id)
    _ensure_owned(skill.profile_id, profile.id)

    updates = collect_updates(payload)
    if "name" in updates:
        normalized = normalize_skill_name(cast(str, updates["name"]))
        await _ensure_skill_name_available(session, profile.id, normalized, exclude_id=skill.id)
        updates["name_normalized"] = normalized
    if "source_evidence_id" in updates:
        await _ensure_evidence_usable(session, cast(uuid.UUID | None, updates["source_evidence_id"]))
    # 内容改了就不再沿用旧简历摘录作为来源；用户显式指定来源时不覆盖。
    await _reattribute_edited_fact(session, skill, updates)

    # 校验必须在"变更后"的状态上进行：只改 claim_status 或只清空证据都可能造成非法组合。
    resulting_status = cast(ClaimStatus, updates.get("claim_status", skill.claim_status))
    resulting_evidence = cast(uuid.UUID | None, updates.get("source_evidence_id", skill.source_evidence_id))
    _ensure_claim_supported(resulting_status, resulting_evidence)

    await apply_versioned_update(session, skill, payload.version, updates)
    await session.commit()
    return skill


async def delete_skill(session: AsyncSession, skill_id: uuid.UUID) -> None:
    """删除技能。

    参数:
        session: 当前会话。
        skill_id: 技能主键。

    异常:
        ResourceNotFoundError: 技能不存在。
        ConflictError: 已被资料修订引用。
    """
    profile = await require_profile(session)
    skill = await _require_fact(session, ProfileSkill, skill_id)
    _ensure_owned(skill.profile_id, profile.id)
    await _ensure_fact_not_referenced(session, ProfileSkill, skill.id)
    await repo.remove(session, skill)
    await session.commit()


# --------------------------------------------------------------------------------------------
# 工作经历
# --------------------------------------------------------------------------------------------


async def create_experience(session: AsyncSession, payload: ExperienceCreate) -> ProfileExperience:
    """新增工作经历。

    参数:
        session: 当前会话。
        payload: 创建请求体。

    返回:
        ProfileExperience: 新记录。
    """
    profile = await require_profile(session)
    await _ensure_evidence_usable(session, payload.source_evidence_id)
    experience = ProfileExperience(
        profile_id=profile.id,
        company=payload.company,
        title=payload.title,
        location=payload.location,
        start_date=payload.start_date,
        end_date=payload.end_date,
        responsibilities=payload.responsibilities,
        achievements=payload.achievements,
        source_evidence_id=payload.source_evidence_id,
        sort_order=payload.sort_order,
    )
    await repo.add(session, experience)
    await session.commit()
    return experience


async def update_experience(
    session: AsyncSession,
    experience_id: uuid.UUID,
    payload: ExperienceUpdate,
) -> ProfileExperience:
    """局部更新工作经历。

    参数:
        session: 当前会话。
        experience_id: 记录主键。
        payload: 局部更新请求体。

    返回:
        ProfileExperience: 更新后的记录。

    异常:
        ResourceNotFoundError: 记录不存在。
        ConflictError: 版本号不匹配。
        ValidationFailedError: 变更后的日期顺序或证据引用非法。
    """
    profile = await require_profile(session)
    experience = await _require_fact(session, ProfileExperience, experience_id)
    _ensure_owned(experience.profile_id, profile.id)

    updates = collect_updates(payload)
    if "source_evidence_id" in updates:
        await _ensure_evidence_usable(session, cast(uuid.UUID | None, updates["source_evidence_id"]))

    start_date = cast(date | None, updates.get("start_date", experience.start_date))
    end_date = cast(date | None, updates.get("end_date", experience.end_date))
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValidationFailedError(
            "结束日期不得早于开始日期。",
            details=[ErrorDetail(field="end_date", reason="变更后 end_date 早于 start_date。")],
        )

    # 内容改了就不再沿用旧简历摘录作为来源；用户显式指定来源时不覆盖。
    await _reattribute_edited_fact(session, experience, updates)

    await apply_versioned_update(session, experience, payload.version, updates)
    await session.commit()
    return experience


async def delete_experience(session: AsyncSession, experience_id: uuid.UUID) -> None:
    """删除工作经历。

    参数:
        session: 当前会话。
        experience_id: 记录主键。

    异常:
        ResourceNotFoundError: 记录不存在。
        ConflictError: 已被资料修订引用。
    """
    profile = await require_profile(session)
    experience = await _require_fact(session, ProfileExperience, experience_id)
    _ensure_owned(experience.profile_id, profile.id)
    await _ensure_fact_not_referenced(session, ProfileExperience, experience.id)
    await _ensure_experience_unlinked(session, experience)
    await repo.remove(session, experience)
    await session.commit()


# --------------------------------------------------------------------------------------------
# 项目
# --------------------------------------------------------------------------------------------


async def create_project(session: AsyncSession, payload: ProjectCreate) -> ProfileProject:
    """新增项目。

    参数:
        session: 当前会话。
        payload: 创建请求体。

    返回:
        ProfileProject: 新记录。
    """
    profile = await require_profile(session)
    await _ensure_evidence_usable(session, payload.source_evidence_id)
    await _ensure_experience_usable(session, profile.id, payload.experience_id)
    project = ProfileProject(
        profile_id=profile.id,
        name=payload.name,
        role=payload.role,
        description=payload.description,
        achievements=payload.achievements,
        tech_stack=payload.tech_stack,
        url=payload.url,
        start_date=payload.start_date,
        end_date=payload.end_date,
        experience_id=payload.experience_id,
        source_evidence_id=payload.source_evidence_id,
        sort_order=payload.sort_order,
    )
    await repo.add(session, project)
    await session.commit()
    return project


async def update_project(session: AsyncSession, project_id: uuid.UUID, payload: ProjectUpdate) -> ProfileProject:
    """局部更新项目。

    参数:
        session: 当前会话。
        project_id: 记录主键。
        payload: 局部更新请求体。

    返回:
        ProfileProject: 更新后的记录。

    异常:
        ResourceNotFoundError: 记录不存在。
        ConflictError: 版本号不匹配。
        ValidationFailedError: 变更后的日期顺序或证据引用非法。
    """
    profile = await require_profile(session)
    project = await _require_fact(session, ProfileProject, project_id)
    _ensure_owned(project.profile_id, profile.id)

    updates = collect_updates(payload)
    if "source_evidence_id" in updates:
        await _ensure_evidence_usable(session, cast(uuid.UUID | None, updates["source_evidence_id"]))
    if "experience_id" in updates:
        await _ensure_experience_usable(session, profile.id, cast(uuid.UUID | None, updates["experience_id"]))

    start_date = cast(date | None, updates.get("start_date", project.start_date))
    end_date = cast(date | None, updates.get("end_date", project.end_date))
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValidationFailedError(
            "结束日期不得早于开始日期。",
            details=[ErrorDetail(field="end_date", reason="变更后 end_date 早于 start_date。")],
        )

    # 内容改了就不再沿用旧简历摘录作为来源；用户显式指定来源时不覆盖。
    await _reattribute_edited_fact(session, project, updates)

    await apply_versioned_update(session, project, payload.version, updates)
    await session.commit()
    return project


async def delete_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    """删除项目。

    参数:
        session: 当前会话。
        project_id: 记录主键。

    异常:
        ResourceNotFoundError: 记录不存在。
        ConflictError: 已被资料修订引用。
    """
    profile = await require_profile(session)
    project = await _require_fact(session, ProfileProject, project_id)
    _ensure_owned(project.profile_id, profile.id)
    await _ensure_fact_not_referenced(session, ProfileProject, project.id)
    await repo.remove(session, project)
    await session.commit()


# --------------------------------------------------------------------------------------------
# 教育
# --------------------------------------------------------------------------------------------


async def create_education(session: AsyncSession, payload: EducationCreate) -> ProfileEducation:
    """新增教育经历。

    参数:
        session: 当前会话。
        payload: 创建请求体。

    返回:
        ProfileEducation: 新记录。
    """
    profile = await require_profile(session)
    await _ensure_evidence_usable(session, payload.source_evidence_id)
    education = ProfileEducation(
        profile_id=profile.id,
        school=payload.school,
        major=payload.major,
        degree=payload.degree,
        start_date=payload.start_date,
        end_date=payload.end_date,
        source_evidence_id=payload.source_evidence_id,
        sort_order=payload.sort_order,
    )
    await repo.add(session, education)
    await session.commit()
    return education


async def update_education(
    session: AsyncSession,
    education_id: uuid.UUID,
    payload: EducationUpdate,
) -> ProfileEducation:
    """局部更新教育经历。

    参数:
        session: 当前会话。
        education_id: 记录主键。
        payload: 局部更新请求体。

    返回:
        ProfileEducation: 更新后的记录。

    异常:
        ResourceNotFoundError: 记录不存在。
        ConflictError: 版本号不匹配。
        ValidationFailedError: 变更后的日期顺序或证据引用非法。
    """
    profile = await require_profile(session)
    education = await _require_fact(session, ProfileEducation, education_id)
    _ensure_owned(education.profile_id, profile.id)

    updates = collect_updates(payload)
    if "source_evidence_id" in updates:
        await _ensure_evidence_usable(session, cast(uuid.UUID | None, updates["source_evidence_id"]))

    start_date = cast(date | None, updates.get("start_date", education.start_date))
    end_date = cast(date | None, updates.get("end_date", education.end_date))
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValidationFailedError(
            "结束日期不得早于开始日期。",
            details=[ErrorDetail(field="end_date", reason="变更后 end_date 早于 start_date。")],
        )

    # 内容改了就不再沿用旧简历摘录作为来源；用户显式指定来源时不覆盖。
    await _reattribute_edited_fact(session, education, updates)

    await apply_versioned_update(session, education, payload.version, updates)
    await session.commit()
    return education


async def delete_education(session: AsyncSession, education_id: uuid.UUID) -> None:
    """删除教育经历。

    参数:
        session: 当前会话。
        education_id: 记录主键。

    异常:
        ResourceNotFoundError: 记录不存在。
        ConflictError: 已被资料修订引用。
    """
    profile = await require_profile(session)
    education = await _require_fact(session, ProfileEducation, education_id)
    _ensure_owned(education.profile_id, profile.id)
    await _ensure_fact_not_referenced(session, ProfileEducation, education.id)
    await repo.remove(session, education)
    await session.commit()


# --------------------------------------------------------------------------------------------
# 语言
# --------------------------------------------------------------------------------------------


async def create_language(session: AsyncSession, payload: LanguageCreate) -> ProfileLanguage:
    """新增语言能力。

    参数:
        session: 当前会话。
        payload: 创建请求体。

    返回:
        ProfileLanguage: 新记录。
    """
    profile = await require_profile(session)
    await _ensure_evidence_usable(session, payload.source_evidence_id)
    language = ProfileLanguage(
        profile_id=profile.id,
        language=payload.language,
        level=payload.level,
        note=payload.note,
        source_evidence_id=payload.source_evidence_id,
        sort_order=payload.sort_order,
    )
    await repo.add(session, language)
    await session.commit()
    return language


async def update_language(
    session: AsyncSession,
    language_id: uuid.UUID,
    payload: LanguageUpdate,
) -> ProfileLanguage:
    """局部更新语言能力。

    参数:
        session: 当前会话。
        language_id: 记录主键。
        payload: 局部更新请求体。

    返回:
        ProfileLanguage: 更新后的记录。

    异常:
        ResourceNotFoundError: 记录不存在。
        ConflictError: 版本号不匹配。
        ValidationFailedError: 证据引用非法。
    """
    profile = await require_profile(session)
    language = await _require_fact(session, ProfileLanguage, language_id)
    _ensure_owned(language.profile_id, profile.id)

    updates = collect_updates(payload)
    if "source_evidence_id" in updates:
        await _ensure_evidence_usable(session, cast(uuid.UUID | None, updates["source_evidence_id"]))

    # 内容改了就不再沿用旧简历摘录作为来源；用户显式指定来源时不覆盖。
    await _reattribute_edited_fact(session, language, updates)

    await apply_versioned_update(session, language, payload.version, updates)
    await session.commit()
    return language


async def delete_language(session: AsyncSession, language_id: uuid.UUID) -> None:
    """删除语言能力。

    参数:
        session: 当前会话。
        language_id: 记录主键。

    异常:
        ResourceNotFoundError: 记录不存在。
        ConflictError: 已被资料修订引用。
    """
    profile = await require_profile(session)
    language = await _require_fact(session, ProfileLanguage, language_id)
    _ensure_owned(language.profile_id, profile.id)
    await _ensure_fact_not_referenced(session, ProfileLanguage, language.id)
    await repo.remove(session, language)
    await session.commit()


# --------------------------------------------------------------------------------------------
# 求职偏好
# --------------------------------------------------------------------------------------------


async def get_preference(session: AsyncSession) -> ProfilePreference | None:
    """读取当前档案的求职偏好。

    参数:
        session: 当前会话。

    返回:
        ProfilePreference | None: 偏好；未设置时为 None。
    """
    profile = await require_profile(session)
    return await repo.get_preference(session, profile.id)


async def upsert_preference(session: AsyncSession, payload: PreferenceUpsert) -> ProfilePreference:
    """创建或整体替换求职偏好。

    参数:
        session: 当前会话。
        payload: 偏好内容。

    返回:
        ProfilePreference: 偏好记录。

    异常:
        ValidationFailedError: 首次创建却提供了 version，或已存在却未提供 version。
        ConflictError: 提供的 version 已过期。

    注意:
        偏好是"当前有效规则"而不是历史事实，因此用整体替换而不是逐字段补丁；
        未提供的字段按"清空"处理，语义与界面上的单个表单一致。
    """
    profile = await require_profile(session)
    existing = await repo.get_preference(session, profile.id)
    values: dict[str, Any] = {
        "target_locations": payload.target_locations,
        "job_types": payload.job_types,
        "salary_min": payload.salary_min,
        "salary_max": payload.salary_max,
        "salary_currency": payload.salary_currency,
        "remote_preference": payload.remote_preference,
        "exclusions": payload.exclusions,
    }

    if existing is None:
        if payload.version is not None:
            raise ValidationFailedError(
                "偏好尚未创建，不应提供 version。",
                details=[ErrorDetail(field="version", reason="首次创建时请省略 version。")],
            )
        preference = ProfilePreference(profile_id=profile.id, **values)
        await repo.add(session, preference)
        await session.commit()
        return preference

    if payload.version is None:
        raise ValidationFailedError(
            "偏好已存在，必须提供 version。",
            details=[ErrorDetail(field="version", reason="整体替换需要乐观锁版本号以避免覆盖他人改动。")],
        )
    await apply_versioned_update(session, existing, payload.version, values)
    await session.commit()
    return existing


# --------------------------------------------------------------------------------------------
# 资料修订
# --------------------------------------------------------------------------------------------


async def list_revisions(session: AsyncSession, *, limit: int) -> Sequence[ProfileRevision]:
    """列出资料修订。

    参数:
        session: 当前会话。
        limit: 返回条数上限。

    返回:
        Sequence[ProfileRevision]: 修订列表，最新在前。
    """
    profile = await require_profile(session)
    return await repo.list_revisions(session, profile.id, limit=limit)


async def create_revision(session: AsyncSession, payload: RevisionCreate) -> ProfileRevision:
    """对当前事实创建一份不可变修订快照。

    参数:
        session: 当前会话。
        payload: 创建原因。

    返回:
        ProfileRevision: 新修订。

    注意:
        修订只在"需要可复现输入"的时点创建（生成简历、发起匹配、用户确认重要变更），
        而不是每次编辑都创建；否则修订表会被输入框的中间状态淹没。
    """
    profile = await require_profile(session)
    revision = ProfileRevision(
        profile_id=profile.id,
        revision_no=await repo.next_revision_no(session, profile.id),
        snapshot_json=build_profile_snapshot(profile),
        reason=payload.reason,
    )
    await repo.add(session, revision)
    await session.commit()
    return revision
