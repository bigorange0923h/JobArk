"""事实归档浏览与恢复；与维护用物理重置分离，保留历史引用。"""

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ResourceNotFoundError
from app.core.responses import ApiResponse, success
from app.core.versioning import apply_versioned_update

from . import service
from .models import ProfileEducation, ProfileExperience, ProfileLanguage, ProfileProject, ProfileSkill
from .router import SessionDep
from .schemas import EducationRead, ExperienceRead, LanguageRead, ProjectRead, SkillRead

Fact = ProfileSkill | ProfileExperience | ProfileProject | ProfileEducation | ProfileLanguage
MODELS: dict[str, type[Fact]] = {
    "skills": ProfileSkill,
    "experiences": ProfileExperience,
    "projects": ProfileProject,
    "educations": ProfileEducation,
    "languages": ProfileLanguage,
}
READS = {
    "skills": SkillRead,
    "experiences": ExperienceRead,
    "projects": ProjectRead,
    "educations": EducationRead,
    "languages": LanguageRead,
}
router = APIRouter(tags=["profile"])


class RestoreInput(BaseModel):
    """恢复只接受归档记录当前版本，冲突时不覆盖有效记录。"""

    version: int = Field(ge=1, description="归档记录当前版本。")


@router.get(
    "/profile/archived-facts",
    summary="查看已归档事实",
    description="读取五类归档事实，历史来源与关联保留；档案不存在返回 404，无写入副作用。",
    response_model=ApiResponse[dict[str, list[dict[str, Any]]]],
)
async def archived_facts(session: SessionDep) -> ApiResponse[dict[str, list[dict[str, Any]]]]:
    """按领域类型返回归档集合，用对应响应模型过滤字段。"""
    profile = await service.require_profile(session)
    result: dict[str, list[dict[str, Any]]] = {}
    for key, model in MODELS.items():
        items = await session.scalars(
            select(model)
            .where(model.profile_id == profile.id, model.archived_at.is_not(None))
            .order_by(model.created_at, model.id)
        )
        result[key] = [READS[key].model_validate(item).model_dump(mode="json") for item in items]
    return success(result)


async def restore_fact(
    session: AsyncSession,
    kind: str,
    fact_id: uuid.UUID,
    version: int,
) -> Fact:
    """按版本恢复归档事实；技能名冲突返回 409，当前关联与历史快照不改写。"""
    model = MODELS.get(kind)
    if model is None:
        raise ResourceNotFoundError("事实类型不存在。")
    profile = await service.require_profile(session)
    entity = await session.get(model, fact_id)
    if entity is None or entity.profile_id != profile.id:
        raise ResourceNotFoundError("事实不存在。")
    if entity.archived_at is None:
        raise ConflictError("该事实已经恢复，请刷新档案。")
    if isinstance(entity, ProfileSkill):
        await service.ensure_skill_name_available(
            session,
            profile.id,
            entity.name_normalized,
            exclude_id=entity.id,
        )
    try:
        await apply_versioned_update(session, entity, version, {"archived_at": None})
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise ConflictError("同名有效技能已存在，不能覆盖恢复。") from error
        raise
    return entity


@router.post(
    "/profile/archived-facts/{kind}/{fact_id}/restore",
    summary="恢复归档事实",
    description="要求归档记录当前 version；不存在返回 404，过期/已恢复/同名技能冲突返回 409，"
    "不改变历史修订，无外部副作用。",
    response_model=ApiResponse[dict[str, Any]],
)
async def restore(
    session: SessionDep,
    kind: str,
    fact_id: uuid.UUID,
    payload: RestoreInput,
) -> ApiResponse[dict[str, Any]]:
    """恢复并返回对应事实响应，不改写来源状态。"""
    entity = await restore_fact(session, kind, fact_id, payload.version)
    return success(READS[kind].model_validate(entity).model_dump(mode="json"))
