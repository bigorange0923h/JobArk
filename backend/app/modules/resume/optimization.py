"""受控 AI 简历优化：只允许重排和选择已有条目，禁止生成新增事实。"""

from copy import deepcopy
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import gateway
from app.core.database import get_session
from app.core.errors import ResourceNotFoundError, ValidationFailedError
from app.core.responses import ApiResponse, success

from .models import ResumeVersion
from .schemas import ResumeDocument, ResumeDraftCreate, ResumeDraftRead
from .service import create_draft

router = APIRouter(tags=["resume"])


class OptimizationRequest(BaseModel):
    """生成前用户确认发送不含联系方式的基线条目。"""

    base_resume_version_id: UUID
    target: str = Field(min_length=1, max_length=2000, description="目标方向或需突出的重点。")
    confirm_external: bool = Field(description="确认发送简历条目到已配置的 AI 网关。")


class Selection(BaseModel):
    """仅允许选择现有索引；未知字段拒绝，防止模型夹带新增内容。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    experiences: list[int]
    projects: list[int]
    skills: list[int]
    educations: list[int]
    languages: list[int]


@router.post(
    "/resumes/{resume_id}/optimize",
    summary="AI 优化候选稿",
    description="仅重排/筛选已有条目，不改写事实；需 confirm_external，失败返回 422/409，基线不存在返回 404。",
    response_model=ApiResponse[ResumeDraftRead],
    status_code=201,
)
async def optimize(
    session: Annotated[AsyncSession, Depends(get_session)], resume_id: UUID, payload: OptimizationRequest
) -> ApiResponse[ResumeDraftRead]:
    """读取固定版本，结束事务后请求选择方案，校验索引并创建待确认稿。"""
    if not payload.confirm_external:
        raise ValidationFailedError("请确认将简历条目发送到已配置的 AI 网关。")
    base = await session.get(ResumeVersion, payload.base_resume_version_id)
    if base is None or base.resume_id != resume_id:
        raise ResourceNotFoundError("基线简历版本不存在。")
    document = deepcopy(base.document_json)
    baseline_id = base.id
    sections = {key: document.get(key, []) for key in Selection.model_fields}
    await session.rollback()
    result = await gateway.generate(
        "resume_select_existing_items", {"target": payload.target, "sections": sections}, Selection.model_json_schema()
    )
    try:
        selection = Selection.model_validate(result)
    except ValidationError as error:
        raise ValidationFailedError("AI 返回的选择方案无效，未创建候选稿。") from error
    for key, indices in selection.model_dump().items():
        items = sections[key]
        if len(indices) != len(set(indices)) or any(type(i) is not int or i < 0 or i >= len(items) for i in indices):
            raise ValidationFailedError("AI 引用了不存在或重复的条目，未创建候选稿。")
        document[key] = [items[i] for i in indices]
    draft = await create_draft(
        session,
        resume_id,
        ResumeDraftCreate(
            document=ResumeDocument.model_validate(document),
            base_resume_version_id=baseline_id,
            generator_name="AI_SELECTION",
            generator_version="selection-v1",
        ),
    )
    return success(ResumeDraftRead.model_validate(draft))
