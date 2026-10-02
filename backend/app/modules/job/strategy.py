"""单人求职策略 API 与可追溯评估事务。"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import ConflictError, ResourceNotFoundError, ValidationFailedError
from app.core.responses import ApiResponse, success
from app.core.versioning import apply_versioned_update

from . import repository, service
from .exclusions import INDUSTRIES, Decision, EvaluationInput, ExclusionReason, ExclusionRule, evaluate, normalize_name
from .models import ExclusionEvaluation, ExclusionException, ExclusionPolicy, JobSnapshot

router = APIRouter(tags=["job-strategy"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class PolicyRead(BaseModel):
    """当前规则集合及乐观锁版本。"""

    version: int
    rules: list[ExclusionRule]


class PolicyWrite(BaseModel):
    """整体保存规则；首次创建版本为 null。"""

    version: int | None = Field(default=None, ge=0)
    rules: list[ExclusionRule] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_rules(self) -> PolicyWrite:
        """拒绝重复 ID 或相同类型与取值。"""
        identities = [
            (rule.kind, normalize_name(rule.value) if rule.kind == "COMPANY_NAME" else rule.value.casefold())
            for rule in self.rules
        ]
        if len({rule.id for rule in self.rules}) != len(self.rules) or len(set(identities)) != len(identities):
            raise ValueError("规则 ID 或类型与取值重复。")
        return self


class FactsWrite(BaseModel):
    """用户确认的公司与岗位分类；未提交字段不修改。"""

    company_version: int
    opportunity_version: int
    nature_code: Literal["OUTSOURCING_PROVIDER", "LABOR_DISPATCH", "OTHER"] | None = None
    industry_code: str | None = None
    outsourcing_arrangement: Literal["OUTSOURCING", "ONSITE", "DIRECT"] | None = None
    confirm: bool

    @model_validator(mode="after")
    def validate_facts(self) -> FactsWrite:
        """分类只接受明确目录及确认，旧文本不作自动映射。"""
        if (
            self.industry_code is not None
            and self.industry_code not in INDUSTRIES
            and not any(self.industry_code in children for children in INDUSTRIES.values())
        ):
            raise ValueError("未知行业代码。")
        if not self.confirm:
            raise ValueError("请明确确认分类资料。")
        return self


class ExceptionWrite(BaseModel):
    """单职位临时例外必须明确确认并说明原因。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    snapshot_id: UUID
    policy_version: int
    company_version: int
    opportunity_version: int
    reason: str = Field(min_length=3, max_length=1000)
    confirm: bool


class EvaluationRead(BaseModel):
    """本次评估与有效例外；例外不改变原判定。"""

    opportunity_id: UUID
    snapshot_id: UUID
    policy_version: int
    company_version: int
    opportunity_version: int
    decision: Decision
    exception_active: bool
    preparation_allowed: bool


async def policy(session: AsyncSession) -> ExclusionPolicy | None:
    """读取单人策略。"""
    return await session.scalar(select(ExclusionPolicy).where(ExclusionPolicy.singleton_key == "default"))


async def current(session: AsyncSession, opportunity_id: UUID, snapshot_id: UUID | None = None) -> EvaluationRead:
    """总是依据现有规则与当前输入计算，查询或评估失败绝不返回通过。"""
    job = await service.require_opportunity(session, opportunity_id)
    company = await repository.get_company(session, job.company_id)
    if company is None:
        raise ResourceNotFoundError("职位关联的公司不存在。")
    postings = await repository.list_postings(session, opportunity_id)
    latest = await repository.current_snapshot(session, opportunity_id)
    if latest is None:
        raise ConflictError("职位尚无 JD 快照，不能准备投递。")
    snapshot = latest if snapshot_id is None else await session.get(JobSnapshot, snapshot_id)
    if snapshot is None or snapshot.posting_id not in {post.id for post in postings}:
        raise ResourceNotFoundError("JD 快照不属于该职位。")
    active = await policy(session)
    rules = [ExclusionRule.model_validate(row) for row in active.rules] if active else []
    decision = evaluate(
        rules,
        EvaluationInput(
            company_name=company.name,
            nature_code=company.nature_code,
            industry_code=company.industry_code,
            outsourcing_arrangement=job.outsourcing_arrangement,
            raw_jd=snapshot.raw_jd,
        ),
    )
    if snapshot.id != latest.id:
        decision = (
            Decision(
                verdict="REVIEW",
                reasons=[*decision.reasons, ExclusionReason(kind="SNAPSHOT", text="所选 JD 不是当前最新快照")],
            )
            if decision.verdict != "EXCLUDED"
            else decision
        )
    exception = await session.scalar(
        select(ExclusionException)
        .where(
            ExclusionException.opportunity_id == job.id,
            ExclusionException.snapshot_id == snapshot.id,
            ExclusionException.policy_version == (active.version if active else 0),
            ExclusionException.company_version == company.version,
            ExclusionException.opportunity_version == job.version,
            ExclusionException.confirmed.is_(True),
        )
        .order_by(ExclusionException.created_at.desc())
        .limit(1)
    )
    if snapshot.id != latest.id:
        exception = None
    return EvaluationRead(
        opportunity_id=job.id,
        snapshot_id=snapshot.id,
        policy_version=active.version if active else 0,
        company_version=company.version,
        opportunity_version=job.version,
        decision=decision,
        exception_active=exception is not None,
        preparation_allowed=decision.verdict == "ELIGIBLE" or exception is not None,
    )


@router.get(
    "/exclusion-policy",
    summary="读取结构化排除规则",
    description="单人本地读取；旧标签不作为规则启用。",
    response_model=ApiResponse[PolicyRead],
)
async def get_policy(session: SessionDep) -> ApiResponse[PolicyRead]:
    """返回当前规则及版本。"""
    row = await policy(session)
    return success(
        PolicyRead(
            version=row.version if row else 0, rules=[ExclusionRule.model_validate(x) for x in row.rules] if row else []
        )
    )


@router.put(
    "/exclusion-policy",
    summary="保存结构化排除规则",
    description="整体替换；版本冲突 409，非法分类 422。",
    response_model=ApiResponse[PolicyRead],
)
async def put_policy(session: SessionDep, payload: PolicyWrite) -> ApiResponse[PolicyRead]:
    """按乐观锁保存用户明确维护的规则。"""
    row = await policy(session)
    if row is None:
        if payload.version not in (None, 0):
            raise ConflictError("规则版本已变化，请刷新。")
        row = ExclusionPolicy(singleton_key="default", rules=[rule.model_dump() for rule in payload.rules])
        session.add(row)
        await session.flush()
    else:
        if payload.version is None:
            raise ConflictError("请提供当前规则版本。")
        await apply_versioned_update(
            session, row, payload.version, {"rules": [rule.model_dump() for rule in payload.rules]}
        )
    await session.commit()
    return success(PolicyRead(version=row.version, rules=payload.rules))


@router.patch(
    "/jobs/{opportunity_id}/exclusion-facts",
    summary="确认公司和岗位分类",
    description="必须确认并提交公司与岗位版本；旧行业文本仍原样保留。",
    response_model=ApiResponse[EvaluationRead],
)
async def confirm_facts(session: SessionDep, opportunity_id: UUID, payload: FactsWrite) -> ApiResponse[EvaluationRead]:
    """只修改用户明确提供的分类，版本变化导致旧例外失效。"""
    job = await service.require_opportunity(session, opportunity_id)
    company = await repository.get_company(session, job.company_id)
    if company is None:
        raise ResourceNotFoundError("公司不存在。")
    company_updates = payload.model_dump(include={"nature_code", "industry_code"}, exclude_unset=True)
    job_updates = payload.model_dump(include={"outsourcing_arrangement"}, exclude_unset=True)
    if not company_updates and not job_updates:
        raise ValidationFailedError("至少确认一项分类。")
    if company_updates:
        await apply_versioned_update(session, company, payload.company_version, company_updates)
    if job_updates:
        await apply_versioned_update(session, job, payload.opportunity_version, job_updates)
    await session.commit()
    return success(await current(session, opportunity_id))


@router.get(
    "/jobs/{opportunity_id}/exclusion",
    summary="预览当前排除判定",
    description="依据当前规则、公司、岗位与 JD；失败不放行。",
    response_model=ApiResponse[EvaluationRead],
)
async def preview(session: SessionDep, opportunity_id: UUID) -> ApiResponse[EvaluationRead]:
    """预览当前确定性结果，不写审计记录。"""
    return success(await current(session, opportunity_id))


@router.post(
    "/jobs/{opportunity_id}/exclusion/evaluations",
    summary="记录当前排除评估",
    description="为投递准备重新计算并保存依据；输入失败不返回通过。",
    response_model=ApiResponse[EvaluationRead],
)
async def record_evaluation(session: SessionDep, opportunity_id: UUID) -> ApiResponse[EvaluationRead]:
    """保存输入版本固定的评估记录。"""
    result = await current(session, opportunity_id)
    session.add(
        ExclusionEvaluation(
            opportunity_id=opportunity_id,
            snapshot_id=result.snapshot_id,
            policy_version=result.policy_version,
            company_version=result.company_version,
            opportunity_version=result.opportunity_version,
            verdict=result.decision.verdict,
            reasons=[item.model_dump() for item in result.decision.reasons],
        )
    )
    await session.commit()
    return success(result)


@router.post(
    "/jobs/{opportunity_id}/exclusion/exception",
    summary="确认单职位临时例外",
    description="需要原因、二次确认和当前全部版本；过期返回 409；不触发外部投递。",
    response_model=ApiResponse[EvaluationRead],
)
async def grant_exception(
    session: SessionDep, opportunity_id: UUID, payload: ExceptionWrite
) -> ApiResponse[EvaluationRead]:
    """仅在当前输入版本一致且用户明确确认时记录例外。"""
    if not payload.confirm:
        raise ValidationFailedError("请明确确认本次单职位例外。")
    result = await current(session, opportunity_id)
    if (payload.snapshot_id, payload.policy_version, payload.company_version, payload.opportunity_version) != (
        result.snapshot_id,
        result.policy_version,
        result.company_version,
        result.opportunity_version,
    ):
        raise ConflictError("规则或职位资料已变化，请重新评估。")
    if result.decision.verdict == "ELIGIBLE":
        raise ConflictError("当前职位无需例外。")
    session.add(
        ExclusionException(
            opportunity_id=opportunity_id,
            snapshot_id=result.snapshot_id,
            policy_version=result.policy_version,
            company_version=result.company_version,
            opportunity_version=result.opportunity_version,
            reason=payload.reason.strip(),
            confirmed=True,
        )
    )
    await session.commit()
    return success(await current(session, opportunity_id))
