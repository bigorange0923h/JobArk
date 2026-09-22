"""JD 解析路由及持久化，原始快照始终不变。"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import gateway
from app.core.database import get_session
from app.core.errors import AppError, ResourceNotFoundError, ValidationFailedError
from app.core.responses import ApiResponse, ORMModel, success

from .analysis import JDAnalysis, parse_jd
from .models import JobParseResult, JobSnapshot

router = APIRouter(prefix="/job-snapshots", tags=["job"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class ParseRequest(BaseModel):
    """选择本地提取或外部 AI；外部发送需用户确认。"""

    engine: Literal["LOCAL", "AI"] = "LOCAL"
    confirm_external: bool = False


class ParseRead(ORMModel):
    """可追溯解析产物，失败仍保留快照引用与安全错误码。"""

    id: UUID
    job_snapshot_id: UUID
    parser_version: str
    status: str
    result_json: dict[str, Any] | None
    failure_code: str | None


@router.post(
    "/{snapshot_id}/parses",
    summary="解析 JD 快照",
    description="本地提取默认开启；AI 需外部发送确认。解析失败保存 FAILED 产物。不存在返回 404，缺确认返回 422。",
    response_model=ApiResponse[ParseRead],
    status_code=201,
)
async def parse_snapshot(session: SessionDep, snapshot_id: UUID, payload: ParseRequest) -> ApiResponse[ParseRead]:
    """结束读事务后解析，校验逐字出处并保存新解析记录。"""
    snapshot = await session.get(JobSnapshot, snapshot_id)
    if snapshot is None:
        raise ResourceNotFoundError("JD 快照不存在。")
    if payload.engine == "AI" and not payload.confirm_external:
        raise ValidationFailedError("请确认将 JD 原文发送到已配置的 AI 网关。")
    raw = snapshot.raw_jd
    await session.rollback()
    result: JDAnalysis | None = None
    failure = None
    try:
        result = (
            parse_jd(raw)
            if payload.engine == "LOCAL"
            else JDAnalysis.model_validate(
                await gateway.generate(
                    "jd_requirements_with_verbatim_quotes", {"raw_jd": raw}, JDAnalysis.model_json_schema()
                )
            )
        )
        if any(
            not item.source_quote.strip() or item.source_quote not in raw or item.text != item.source_quote
            for item in result.requirements
        ):
            raise ValueError("unverified quote")
    except AppError, ValidationError, ValueError:
        failure = "JD_PARSE_FAILED"
        result = None
    entity = JobParseResult(
        job_snapshot_id=snapshot_id,
        parser_version="literal-lines-v1" if payload.engine == "LOCAL" else "ai-quotes-v1",
        status="FAILED" if failure else "PARSED",
        result_json=result.model_dump() if result else None,
        failure_code=failure,
    )
    session.add(entity)
    await session.commit()
    return success(ParseRead.model_validate(entity))


@router.get(
    "/{snapshot_id}/parses",
    summary="JD 解析历史",
    description="读取独立解析产物；失败内容不替换原始快照。",
    response_model=ApiResponse[list[ParseRead]],
)
async def list_parses(session: SessionDep, snapshot_id: UUID) -> ApiResponse[list[ParseRead]]:
    """读取指定快照的解析历史，无写入副作用。"""
    if await session.get(JobSnapshot, snapshot_id) is None:
        raise ResourceNotFoundError("JD 快照不存在。")
    rows = await session.scalars(
        select(JobParseResult)
        .where(JobParseResult.job_snapshot_id == snapshot_id)
        .order_by(JobParseResult.created_at.desc())
    )
    return success([ParseRead.model_validate(row) for row in rows])
