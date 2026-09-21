"""Profile 领域的 HTTP 接口。

约定：

- 所有响应都包裹在统一契约中（见 ADR 0001），失败由 `app/core/exception_handlers.py` 统一构造。
- 路由只做参数绑定与响应包装，业务规则全在 `service.py`；这里不出现 `try/except`。
- 事务、乐观锁与引用完整性检查由服务层负责，路由不感知会话细节。
- 单用户本地工具，V1 没有认证与权限；所有接口都作用于唯一的个人档案。

主要错误映射（细节见 ADR 0001 的错误码表）：

- `RESOURCE_NOT_FOUND`：档案或指定记录不存在。
- `CONFLICT`：档案已存在、版本号过期、技能名重复、记录被资料修订引用。
- `VALIDATION_ERROR`：字段校验失败、证据引用无效、标记为已验证但缺少证据、日期顺序非法。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import ResourceNotFoundError
from app.core.responses import ApiResponse, success

from . import service
from .schemas import (
    EducationCreate,
    EducationRead,
    EducationUpdate,
    EvidenceCreate,
    EvidenceRead,
    EvidenceUpdate,
    ExperienceCreate,
    ExperienceRead,
    ExperienceUpdate,
    LanguageCreate,
    LanguageRead,
    LanguageUpdate,
    PreferenceRead,
    PreferenceUpsert,
    ProfileCreate,
    ProfileRead,
    ProfileUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    ResourceRef,
    RevisionCreate,
    RevisionRead,
    SkillCreate,
    SkillRead,
    SkillUpdate,
)

router = APIRouter(tags=["profile"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "/profile",
    summary="读取个人档案",
    description="返回档案根信息、全部证据、事实与求职偏好。档案尚未创建时返回 404。",
    response_model=ApiResponse[ProfileRead],
)
async def get_profile(session: SessionDep) -> ApiResponse[ProfileRead]:
    """读取唯一的个人档案聚合。

    返回:
        ApiResponse[ProfileRead]: 档案聚合。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
    """
    profile = await service.require_profile(session)
    return success(ProfileRead.model_validate(profile))


@router.post(
    "/profile",
    summary="创建个人档案",
    description="首次填写档案根信息。V1 只允许一份档案，重复创建返回 409。",
    response_model=ApiResponse[ProfileRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_profile(session: SessionDep, payload: ProfileCreate) -> ApiResponse[ProfileRead]:
    """创建单例档案。

    参数:
        session: 请求级数据库会话。
        payload: 档案根信息。

    返回:
        ApiResponse[ProfileRead]: 新建的档案。

    异常:
        CONFLICT: 档案已存在。
    """
    profile = await service.create_profile(session, payload)
    return success(ProfileRead.model_validate(profile))


@router.patch(
    "/profile",
    summary="更新个人档案",
    description="局部更新档案根信息；必须提交当前 version，版本过期返回 409。",
    response_model=ApiResponse[ProfileRead],
)
async def update_profile(session: SessionDep, payload: ProfileUpdate) -> ApiResponse[ProfileRead]:
    """局部更新档案根信息。

    参数:
        session: 请求级数据库会话。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ApiResponse[ProfileRead]: 更新后的档案。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
        CONFLICT: 版本号已过期。
    """
    profile = await service.update_profile(session, payload)
    return success(ProfileRead.model_validate(profile))


# --------------------------------------------------------------------------------------------
# 证据
# --------------------------------------------------------------------------------------------


@router.get(
    "/profile/evidences",
    summary="列出证据",
    description="默认排除已归档证据；`include_archived=true` 可一并返回。",
    response_model=ApiResponse[list[EvidenceRead]],
)
async def list_evidences(
    session: SessionDep,
    include_archived: Annotated[bool, Query(description="是否包含已归档证据。")] = False,
) -> ApiResponse[list[EvidenceRead]]:
    """列出当前档案的证据。

    参数:
        session: 请求级数据库会话。
        include_archived: 是否包含已归档证据。

    返回:
        ApiResponse[list[EvidenceRead]]: 证据列表。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
    """
    evidences = await service.list_evidences(session, include_archived=include_archived)
    return success([EvidenceRead.model_validate(evidence) for evidence in evidences])


@router.post(
    "/profile/evidences",
    summary="新增证据",
    description="记录一条可追溯的真实信息来源；后续事实通过 source_evidence_id 引用它。",
    response_model=ApiResponse[EvidenceRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_evidence(session: SessionDep, payload: EvidenceCreate) -> ApiResponse[EvidenceRead]:
    """新增证据。

    参数:
        session: 请求级数据库会话。
        payload: 证据内容。

    返回:
        ApiResponse[EvidenceRead]: 新建证据。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
    """
    evidence = await service.create_evidence(session, payload)
    return success(EvidenceRead.model_validate(evidence))


@router.patch(
    "/profile/evidences/{evidence_id}",
    summary="更新证据",
    description="局部更新证据；必须提交当前 version。",
    response_model=ApiResponse[EvidenceRead],
)
async def update_evidence(
    session: SessionDep,
    evidence_id: uuid.UUID,
    payload: EvidenceUpdate,
) -> ApiResponse[EvidenceRead]:
    """局部更新证据。

    参数:
        session: 请求级数据库会话。
        evidence_id: 证据主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ApiResponse[EvidenceRead]: 更新后的证据。

    异常:
        RESOURCE_NOT_FOUND: 证据不存在。
        CONFLICT: 版本号已过期。
    """
    evidence = await service.update_evidence(session, evidence_id, payload)
    return success(EvidenceRead.model_validate(evidence))


@router.delete(
    "/profile/evidences/{evidence_id}",
    summary="归档证据",
    description="把证据标记为已归档（写 archived_at），不物理删除：证据可能被多条事实引用，删除会破坏这些引用。",
    response_model=ApiResponse[EvidenceRead],
)
async def archive_evidence(session: SessionDep, evidence_id: uuid.UUID) -> ApiResponse[EvidenceRead]:
    """归档证据。

    参数:
        session: 请求级数据库会话。
        evidence_id: 证据主键。

    返回:
        ApiResponse[EvidenceRead]: 归档后的证据。

    异常:
        RESOURCE_NOT_FOUND: 证据不存在。
    """
    evidence = await service.archive_evidence(session, evidence_id)
    return success(EvidenceRead.model_validate(evidence))


# --------------------------------------------------------------------------------------------
# 技能
# --------------------------------------------------------------------------------------------


@router.post(
    "/profile/skills",
    summary="新增技能",
    description="同一档案内规范化技能名唯一；标记为 VERIFIED 时必须提供 source_evidence_id。",
    response_model=ApiResponse[SkillRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_skill(session: SessionDep, payload: SkillCreate) -> ApiResponse[SkillRead]:
    """新增技能。

    参数:
        session: 请求级数据库会话。
        payload: 技能内容。

    返回:
        ApiResponse[SkillRead]: 新建技能。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
        CONFLICT: 同名技能已存在。
        VALIDATION_ERROR: 证据无效或缺少证据却标记为已验证。
    """
    skill = await service.create_skill(session, payload)
    return success(SkillRead.model_validate(skill))


@router.patch(
    "/profile/skills/{skill_id}",
    summary="更新技能",
    description="局部更新技能；校验变更后的状态与证据是否匹配，例如清空证据时不能保留 VERIFIED。",
    response_model=ApiResponse[SkillRead],
)
async def update_skill(session: SessionDep, skill_id: uuid.UUID, payload: SkillUpdate) -> ApiResponse[SkillRead]:
    """局部更新技能。

    参数:
        session: 请求级数据库会话。
        skill_id: 技能主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ApiResponse[SkillRead]: 更新后的技能。

    异常:
        RESOURCE_NOT_FOUND: 技能不存在。
        CONFLICT: 版本号已过期或改名后与他人重复。
        VALIDATION_ERROR: 变更后的状态与证据不匹配。
    """
    skill = await service.update_skill(session, skill_id, payload)
    return success(SkillRead.model_validate(skill))


@router.delete(
    "/profile/skills/{skill_id}",
    summary="删除技能",
    description="物理删除；若该技能已被任何资料修订引用，返回 409 并列出引用它的修订号。",
    response_model=ApiResponse[ResourceRef],
)
async def delete_skill(session: SessionDep, skill_id: uuid.UUID) -> ApiResponse[ResourceRef]:
    """删除技能。

    参数:
        session: 请求级数据库会话。
        skill_id: 技能主键。

    返回:
        ApiResponse[ResourceRef]: 被删除记录的主键。

    异常:
        RESOURCE_NOT_FOUND: 技能不存在。
        CONFLICT: 已被资料修订引用。
    """
    await service.delete_skill(session, skill_id)
    return success(ResourceRef(id=skill_id))


# --------------------------------------------------------------------------------------------
# 工作经历
# --------------------------------------------------------------------------------------------


@router.post(
    "/profile/experiences",
    summary="新增工作经历",
    description="记录一段工作经历；结束日期早于开始日期返回 422。",
    response_model=ApiResponse[ExperienceRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_experience(session: SessionDep, payload: ExperienceCreate) -> ApiResponse[ExperienceRead]:
    """新增工作经历。

    参数:
        session: 请求级数据库会话。
        payload: 经历内容。

    返回:
        ApiResponse[ExperienceRead]: 新建记录。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
        VALIDATION_ERROR: 日期顺序非法或证据引用无效。
    """
    experience = await service.create_experience(session, payload)
    return success(ExperienceRead.model_validate(experience))


@router.patch(
    "/profile/experiences/{experience_id}",
    summary="更新工作经历",
    description="局部更新；校验变更后的日期顺序与证据引用。",
    response_model=ApiResponse[ExperienceRead],
)
async def update_experience(
    session: SessionDep,
    experience_id: uuid.UUID,
    payload: ExperienceUpdate,
) -> ApiResponse[ExperienceRead]:
    """局部更新工作经历。

    参数:
        session: 请求级数据库会话。
        experience_id: 记录主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ApiResponse[ExperienceRead]: 更新后的记录。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
        CONFLICT: 版本号已过期。
        VALIDATION_ERROR: 日期顺序非法或证据引用无效。
    """
    experience = await service.update_experience(session, experience_id, payload)
    return success(ExperienceRead.model_validate(experience))


@router.delete(
    "/profile/experiences/{experience_id}",
    summary="删除工作经历",
    description="物理删除；被资料修订引用时返回 409。",
    response_model=ApiResponse[ResourceRef],
)
async def delete_experience(session: SessionDep, experience_id: uuid.UUID) -> ApiResponse[ResourceRef]:
    """删除工作经历。

    参数:
        session: 请求级数据库会话。
        experience_id: 记录主键。

    返回:
        ApiResponse[ResourceRef]: 被删除记录的主键。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
        CONFLICT: 已被资料修订引用。
    """
    await service.delete_experience(session, experience_id)
    return success(ResourceRef(id=experience_id))


# --------------------------------------------------------------------------------------------
# 项目
# --------------------------------------------------------------------------------------------


@router.post(
    "/profile/projects",
    summary="新增项目",
    description="工作项目与个人项目都可以记录，不强制绑定到某段工作经历。",
    response_model=ApiResponse[ProjectRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_project(session: SessionDep, payload: ProjectCreate) -> ApiResponse[ProjectRead]:
    """新增项目。

    参数:
        session: 请求级数据库会话。
        payload: 项目内容。

    返回:
        ApiResponse[ProjectRead]: 新建记录。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
        VALIDATION_ERROR: 日期顺序非法或证据引用无效。
    """
    project = await service.create_project(session, payload)
    return success(ProjectRead.model_validate(project))


@router.patch(
    "/profile/projects/{project_id}",
    summary="更新项目",
    description="局部更新；校验变更后的日期顺序与证据引用。",
    response_model=ApiResponse[ProjectRead],
)
async def update_project(
    session: SessionDep,
    project_id: uuid.UUID,
    payload: ProjectUpdate,
) -> ApiResponse[ProjectRead]:
    """局部更新项目。

    参数:
        session: 请求级数据库会话。
        project_id: 记录主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ApiResponse[ProjectRead]: 更新后的记录。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
        CONFLICT: 版本号已过期。
        VALIDATION_ERROR: 日期顺序非法或证据引用无效。
    """
    project = await service.update_project(session, project_id, payload)
    return success(ProjectRead.model_validate(project))


@router.delete(
    "/profile/projects/{project_id}",
    summary="删除项目",
    description="物理删除；被资料修订引用时返回 409。",
    response_model=ApiResponse[ResourceRef],
)
async def delete_project(session: SessionDep, project_id: uuid.UUID) -> ApiResponse[ResourceRef]:
    """删除项目。

    参数:
        session: 请求级数据库会话。
        project_id: 记录主键。

    返回:
        ApiResponse[ResourceRef]: 被删除记录的主键。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
        CONFLICT: 已被资料修订引用。
    """
    await service.delete_project(session, project_id)
    return success(ResourceRef(id=project_id))


# --------------------------------------------------------------------------------------------
# 教育
# --------------------------------------------------------------------------------------------


@router.post(
    "/profile/educations",
    summary="新增教育经历",
    description="学历信息以用户录入或可信证据为准，不由系统推断。",
    response_model=ApiResponse[EducationRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_education(session: SessionDep, payload: EducationCreate) -> ApiResponse[EducationRead]:
    """新增教育经历。

    参数:
        session: 请求级数据库会话。
        payload: 教育经历内容。

    返回:
        ApiResponse[EducationRead]: 新建记录。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
        VALIDATION_ERROR: 日期顺序非法或证据引用无效。
    """
    education = await service.create_education(session, payload)
    return success(EducationRead.model_validate(education))


@router.patch(
    "/profile/educations/{education_id}",
    summary="更新教育经历",
    description="局部更新；校验变更后的日期顺序与证据引用。",
    response_model=ApiResponse[EducationRead],
)
async def update_education(
    session: SessionDep,
    education_id: uuid.UUID,
    payload: EducationUpdate,
) -> ApiResponse[EducationRead]:
    """局部更新教育经历。

    参数:
        session: 请求级数据库会话。
        education_id: 记录主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ApiResponse[EducationRead]: 更新后的记录。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
        CONFLICT: 版本号已过期。
        VALIDATION_ERROR: 日期顺序非法或证据引用无效。
    """
    education = await service.update_education(session, education_id, payload)
    return success(EducationRead.model_validate(education))


@router.delete(
    "/profile/educations/{education_id}",
    summary="删除教育经历",
    description="物理删除；被资料修订引用时返回 409。",
    response_model=ApiResponse[ResourceRef],
)
async def delete_education(session: SessionDep, education_id: uuid.UUID) -> ApiResponse[ResourceRef]:
    """删除教育经历。

    参数:
        session: 请求级数据库会话。
        education_id: 记录主键。

    返回:
        ApiResponse[ResourceRef]: 被删除记录的主键。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
        CONFLICT: 已被资料修订引用。
    """
    await service.delete_education(session, education_id)
    return success(ResourceRef(id=education_id))


# --------------------------------------------------------------------------------------------
# 语言
# --------------------------------------------------------------------------------------------


@router.post(
    "/profile/languages",
    summary="新增语言能力",
    description="语言水平不得由系统推断为已验证事实；需要凭据时请先录入证据再引用。",
    response_model=ApiResponse[LanguageRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_language(session: SessionDep, payload: LanguageCreate) -> ApiResponse[LanguageRead]:
    """新增语言能力。

    参数:
        session: 请求级数据库会话。
        payload: 语言能力内容。

    返回:
        ApiResponse[LanguageRead]: 新建记录。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
        VALIDATION_ERROR: 证据引用无效。
    """
    language = await service.create_language(session, payload)
    return success(LanguageRead.model_validate(language))


@router.patch(
    "/profile/languages/{language_id}",
    summary="更新语言能力",
    description="局部更新；校验证据引用。",
    response_model=ApiResponse[LanguageRead],
)
async def update_language(
    session: SessionDep,
    language_id: uuid.UUID,
    payload: LanguageUpdate,
) -> ApiResponse[LanguageRead]:
    """局部更新语言能力。

    参数:
        session: 请求级数据库会话。
        language_id: 记录主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ApiResponse[LanguageRead]: 更新后的记录。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
        CONFLICT: 版本号已过期。
        VALIDATION_ERROR: 证据引用无效。
    """
    language = await service.update_language(session, language_id, payload)
    return success(LanguageRead.model_validate(language))


@router.delete(
    "/profile/languages/{language_id}",
    summary="删除语言能力",
    description="物理删除；被资料修订引用时返回 409。",
    response_model=ApiResponse[ResourceRef],
)
async def delete_language(session: SessionDep, language_id: uuid.UUID) -> ApiResponse[ResourceRef]:
    """删除语言能力。

    参数:
        session: 请求级数据库会话。
        language_id: 记录主键。

    返回:
        ApiResponse[ResourceRef]: 被删除记录的主键。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
        CONFLICT: 已被资料修订引用。
    """
    await service.delete_language(session, language_id)
    return success(ResourceRef(id=language_id))


# --------------------------------------------------------------------------------------------
# 求职偏好
# --------------------------------------------------------------------------------------------


@router.get(
    "/profile/preference",
    summary="读取求职偏好",
    description="偏好属于可变规则而非履历事实；尚未设置时返回 404。",
    response_model=ApiResponse[PreferenceRead],
)
async def get_preference(session: SessionDep) -> ApiResponse[PreferenceRead]:
    """读取求职偏好。

    参数:
        session: 请求级数据库会话。

    返回:
        ApiResponse[PreferenceRead]: 偏好内容。

    异常:
        RESOURCE_NOT_FOUND: 档案或偏好尚未创建。
    """
    preference = await service.get_preference(session)
    if preference is None:
        raise ResourceNotFoundError("求职偏好尚未设置。")
    return success(PreferenceRead.model_validate(preference))


@router.put(
    "/profile/preference",
    summary="设置求职偏好",
    description="整体替换偏好：未提交的字段按清空处理。已存在时必须提交当前 version。",
    response_model=ApiResponse[PreferenceRead],
)
async def upsert_preference(session: SessionDep, payload: PreferenceUpsert) -> ApiResponse[PreferenceRead]:
    """创建或整体替换求职偏好。

    参数:
        session: 请求级数据库会话。
        payload: 偏好内容；已存在时需带 version。

    返回:
        ApiResponse[PreferenceRead]: 保存后的偏好。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
        CONFLICT: 版本号已过期。
        VALIDATION_ERROR: 首次创建却提供 version，或已存在却未提供。
    """
    preference = await service.upsert_preference(session, payload)
    return success(PreferenceRead.model_validate(preference))


# --------------------------------------------------------------------------------------------
# 资料修订
# --------------------------------------------------------------------------------------------


@router.get(
    "/profile/revisions",
    summary="列出资料修订",
    description="修订不可变，按修订号倒序返回；匹配与简历只能引用修订而不是当前事实。",
    response_model=ApiResponse[list[RevisionRead]],
)
async def list_revisions(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100, description="返回条数上限。")] = 20,
) -> ApiResponse[list[RevisionRead]]:
    """列出资料修订。

    参数:
        session: 请求级数据库会话。
        limit: 返回条数上限。

    返回:
        ApiResponse[list[RevisionRead]]: 修订列表。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
    """
    revisions = await service.list_revisions(session, limit=limit)
    return success([RevisionRead.model_validate(revision) for revision in revisions])


@router.post(
    "/profile/revisions",
    summary="创建资料修订",
    description="对当前事实生成一份不可变快照，作为后续简历生成与匹配的可复现输入；不会修改任何现有事实。",
    response_model=ApiResponse[RevisionRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_revision(session: SessionDep, payload: RevisionCreate) -> ApiResponse[RevisionRead]:
    """创建资料修订。

    参数:
        session: 请求级数据库会话。
        payload: 创建原因。

    返回:
        ApiResponse[RevisionRead]: 新修订。

    异常:
        RESOURCE_NOT_FOUND: 档案尚未创建。
    """
    revision = await service.create_revision(session, payload)
    return success(RevisionRead.model_validate(revision))
