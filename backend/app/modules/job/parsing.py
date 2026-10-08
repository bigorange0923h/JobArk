"""JD 解析路由及持久化，原始快照始终不变。"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai_service
from app.ai.llm import gateway
from app.core.config import get_settings
from app.core.database import get_session
from app.core.errors import AppError, ConflictError, ResourceNotFoundError, ValidationFailedError
from app.core.responses import ApiResponse, ORMModel, success

from . import strategy
from .analysis import PARSER_VERSION, JDAnalysis, parse_jd, validate_source
from .models import JobParseResult, JobPosting, JobSnapshot

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
        raise ValidationFailedError("请确认将 JD 原文发送到已配置的大模型服务。")
    if payload.engine == "AI":
        posting = await session.get(JobPosting, snapshot.posting_id)
        if posting is not None:
            gate = await strategy.current(session, posting.opportunity_id, snapshot_id)
            if gate.decision.verdict == "EXCLUDED":
                raise ConflictError("已命中排除规则，外部解析已停止；可以继续本地提取。")
    raw = snapshot.raw_jd
    await session.rollback()
    # 默认模型解析必须放在"解析失败可保存为 FAILED 产物"的 try 之外：
    # 没有默认模型属于配置缺失（409），不是 JD 解析失败，不能被吞成一条失败记录。
    config: gateway.ResolvedAiModel | None = None
    if payload.engine == "AI":
        config = await ai_service.resolve_default_model(session, get_settings())
        # 解析默认模型开启新的读事务；等待网络前必须再次结束事务（见 ADR 0002）。
        await session.rollback()
    result: JDAnalysis | None = None
    failure = None
    try:
        if config is None:
            result = parse_jd(raw)
        else:
            result = JDAnalysis.model_validate(
                await gateway.generate(
                    config,
                    "jd_requirements_with_verbatim_quotes",
                    {"raw_jd": raw},
                    JDAnalysis.model_json_schema(),
                )
            )
        validate_source(result, raw)
    except AppError, ValidationError, ValueError:
        failure = "JD_PARSE_FAILED"
        result = None
    entity = JobParseResult(
        job_snapshot_id=snapshot_id,
        parser_version=PARSER_VERSION if payload.engine == "LOCAL" else "ai-conditions-v2",
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
