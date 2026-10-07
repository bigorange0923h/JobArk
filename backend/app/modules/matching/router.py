"""可解释的本地匹配：档案事实的字面检索，命中只说明"档案里有这条事实"，不说明已核实。

命中状态刻意点名事实而不是证据：用户自述的未验证技能同样可能命中岗位关键词，报告必须说清这一点，
并且不能暗示能力、熟练度、年限或整项条件已经核实，也不输出招聘概率。
"""

import hashlib
import json
import re
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import ResourceNotFoundError, ValidationFailedError
from app.core.responses import ApiResponse, ORMModel, success
from app.modules.job.analysis import parse_jd
from app.modules.job.models import JobSnapshot
from app.modules.profile.models import ProfileRevision
from app.modules.resume.models import ResumeVersion

from . import service as analysis_service
from .models import MatchResult

router = APIRouter(prefix="/matches", tags=["matching"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class MatchCreate(BaseModel):
    """匹配必须指定版本化输入；选择简历时要求同一资料修订。"""

    job_snapshot_id: UUID
    profile_revision_id: UUID
    resume_version_id: UUID | None = None
    parse_result_id: UUID | None = Field(default=None, description="新分析必须显式引用成功解析；省略沿用旧字面报告。")
    engine: str = Field(default="LOCAL", pattern="^(LOCAL|AI)$", description="本地或经确认的模型条件评估。")
    confirm_external: bool = Field(default=False, description="仅用于本次 JD 和必要履历摘要外发。")
    expected_service: str | None = Field(
        default=None, max_length=2048, description="确认时展示的服务商端点；变化拒绝外发。"
    )
    expected_model: str | None = Field(default=None, max_length=200, description="确认时展示的模型标识。")


class MatchRead(ORMModel):
    """不可变分析报告。"""

    id: UUID
    created_at: datetime
    job_snapshot_id: UUID
    profile_revision_id: UUID
    resume_version_id: UUID | None
    parse_result_id: UUID | None = None
    is_stale: bool | None = Field(default=None, description="新报告相对现有相关输入是否过期；旧报告未知。")
    match_kind: str
    engine_name: str
    engine_version: str
    input_fingerprint: str
    report_json: dict[str, Any] = Field(description="版本化条件、事实引用、策略、参考范围与未知项；旧报告不回填分数。")


def _evidence_titles(profile: dict[str, Any]) -> dict[str, str]:
    """返回资料修订快照里的证据 id → 标题映射。

    参数:
        profile: 资料修订快照。

    返回:
        dict[str, str]: 证据主键到标题的映射；用于让报告能说明命中事实的来源。

    注意:
        只用于展示：报告不因为存在来源记录就改变命中判定。
    """
    return {str(evidence.get("id")): str(evidence.get("title") or "") for evidence in profile.get("evidences", [])}


def build_report(jd: str, profile: dict[str, Any], document: dict[str, Any] | None) -> dict[str, Any]:
    """只识别资料中已有技能名的字面匹配；不把出现技能等同于满足整项要求。

    参数:
        jd: JD 原文。
        profile: 资料修订快照（含事实与来源证据摘要）。
        document: 可选的简历版本文档；提供时会额外要求该技能事实已被简历表达。

    返回:
        dict[str, Any]: 逐条条件的命中情况。`status` 取值语义：
            `FACT_FOUND` 仅在档案中找到字面匹配的事实、且该事实未挂来源记录；
            `EVIDENCE_ATTACHED` 命中且该事实另挂了来源证据记录（仍然只是字面匹配）；
            `UNKNOWN` 未在档案中找到对应事实（不等同于不满足）。

    注意:
        命中判定与 `claim_status`、是否挂证据**无关**：用户自述的未验证技能同样会命中，报告如实
        呈现其状态与来源，由读者判断可信度。分数恒为空，不输出招聘概率。
    """
    analysis = parse_jd(jd)
    titles = _evidence_titles(profile)
    rows: list[dict[str, Any]] = []
    skills: list[dict[str, Any]] = profile.get("skills", [])
    expressed: list[dict[str, Any]] = document.get("skills", []) if document else []
    for requirement in analysis.requirements:
        evidence: list[dict[str, Any]] = []
        for skill in skills:
            name = str(skill.get("name", ""))
            # 英文技能使用标识符边界，避免 Java 命中 JavaScript；中文保持字面检索。
            pattern = rf"(?<![A-Za-z0-9_+#]){re.escape(name)}(?![A-Za-z0-9_+#])"
            if not name or not re.search(pattern, requirement.text, re.IGNORECASE):
                continue
            if document is not None and not any(item.get("source_fact_id") == skill.get("id") for item in expressed):
                continue
            evidence_id = skill.get("source_evidence_id")
            evidence.append(
                {
                    "fact_id": skill["id"],
                    "evidence_id": evidence_id,
                    "evidence_title": titles.get(str(evidence_id), "") if evidence_id else "",
                    "name": name,
                    "claim_status": skill.get("claim_status", "UNVERIFIED"),
                }
            )
        has_source = any(item["evidence_id"] for item in evidence)
        if not evidence:
            status = "UNKNOWN"
        elif has_source:
            status = "EVIDENCE_ATTACHED"
        else:
            status = "FACT_FOUND"
        rows.append(
            {
                **requirement.model_dump(),
                "status": status,
                "evidence": evidence,
                "explanation": "命中档案中的技能事实（字面匹配）：这是名称层面的对应，"
                "不代表能力、熟练度、年限或整项条件已核实。"
                if evidence
                else "未找到可核验依据，不等同于不满足。",
            }
        )
    return {
        "overall_score": None,
        "parser_version": analysis.parser_version,
        "requirements": rows,
        "hard_constraints": [row for row in rows if row["hard"]],
        "gaps": [row["text"] for row in rows if not row["evidence"]],
        "uncertainties": analysis.uncertainties + ["本引擎未校准语义匹配和硬性淘汰规则。"],
    }


@router.post(
    "",
    summary="生成可解释匹配",
    description=(
        "固定快照与资料修订，引用不存在返回404，不一致返回422。省略解析引用沿用旧本地报告。"
        "指定成功解析生成六维参考区间并冻结策略；AI 需本次外发确认，缺配置409，校验失败422。"
        "命中状态区分字面命中（`FACT_FOUND` 未挂来源记录、`EVIDENCE_ATTACHED` 另挂来源记录）与 `UNKNOWN`；"
        "两种命中都只是名称层面的对应，不代表能力、熟练度、年限或整项条件已核实，也不输出招聘概率。"
        "是否挂来源证据不影响命中判定。"
    ),
    response_model=ApiResponse[MatchRead],
    status_code=201,
)
async def create_match(session: SessionDep, payload: MatchCreate) -> ApiResponse[MatchRead]:
    """校验固定输入并保存不可变报告；模型外发仅在明确确认且策略未排除时执行。"""
    if payload.parse_result_id is not None:
        entity = await analysis_service.create_analysis(
            session,
            payload.job_snapshot_id,
            payload.profile_revision_id,
            payload.resume_version_id,
            payload.parse_result_id,
            payload.engine,
            payload.confirm_external,
            payload.expected_service,
            payload.expected_model,
        )
        return success(MatchRead.model_validate(entity))
    if payload.engine == "AI":
        raise ValidationFailedError("模型分析须选择成功的 JD 解析产物。")
    snapshot = await session.get(JobSnapshot, payload.job_snapshot_id)
    revision = await session.get(ProfileRevision, payload.profile_revision_id)
    if snapshot is None or revision is None:
        raise ResourceNotFoundError("JD 快照或资料修订不存在。")
    document = None
    if payload.resume_version_id:
        version = await session.get(ResumeVersion, payload.resume_version_id)
        if version is None:
            raise ResourceNotFoundError("简历版本不存在。")
        if version.profile_revision_id != revision.id:
            raise ValidationFailedError("简历版本与所选资料修订不一致。")
        document = version.document_json
    fingerprint = hashlib.sha256(
        json.dumps({**payload.model_dump(mode="json"), "engine": "literal-evidence-v1"}, sort_keys=True).encode()
    ).hexdigest()
    entity = MatchResult(
        job_snapshot_id=snapshot.id,
        profile_revision_id=revision.id,
        resume_version_id=payload.resume_version_id,
        match_kind="RESUME" if document is not None else "PROFILE",
        engine_name="LOCAL_LITERAL",
        engine_version="literal-evidence-v1",
        input_fingerprint=fingerprint,
        report_json=build_report(snapshot.raw_jd, revision.snapshot_json, document),
    )
    session.add(entity)
    await session.commit()
    return success(MatchRead.model_validate(entity))


@router.get(
    "",
    summary="匹配历史",
    description="按时间倒序读取不可变历史报告，无外部调用。",
    response_model=ApiResponse[list[MatchRead]],
)
async def list_matches(session: SessionDep) -> ApiResponse[list[MatchRead]]:
    """返回历史报告及输入引用。"""
    rows = await session.scalars(select(MatchResult).order_by(MatchResult.created_at.desc()))
    results: list[MatchRead] = []
    for row in rows:
        result = MatchRead.model_validate(row)
        result.is_stale = await analysis_service.is_stale(session, row)
        results.append(result)
    return success(results)
