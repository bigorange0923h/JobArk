"""可解释的本地匹配：精确证据检索，缺证据归为未知，不输出招聘概率。"""

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

from .models import MatchResult

router = APIRouter(prefix="/matches", tags=["matching"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class MatchCreate(BaseModel):
    """匹配必须指定版本化输入；选择简历时要求同一资料修订。"""

    job_snapshot_id: UUID
    profile_revision_id: UUID
    resume_version_id: UUID | None = None


class MatchRead(ORMModel):
    """不可变分析报告。"""

    id: UUID
    created_at: datetime
    job_snapshot_id: UUID
    profile_revision_id: UUID
    resume_version_id: UUID | None
    match_kind: str
    engine_name: str
    engine_version: str
    input_fingerprint: str
    report_json: dict[str, Any] = Field(description="条件、事实引用、缺口和未知项，不包含总分。")


def build_report(jd: str, profile: dict[str, Any], document: dict[str, Any] | None) -> dict[str, Any]:
    """只识别资料中已有技能名的字面证据；不把出现技能等同于满足整项要求。"""
    analysis = parse_jd(jd)
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
            evidence.append(
                {
                    "fact_id": skill["id"],
                    "evidence_id": skill.get("source_evidence_id"),
                    "name": name,
                    "claim_status": skill.get("claim_status", "UNVERIFIED"),
                }
            )
        rows.append(
            {
                **requirement.model_dump(),
                "status": "EVIDENCE_FOUND" if evidence else "UNKNOWN",
                "evidence": evidence,
                "explanation": "找到技能字面引用，熟练度、年限及完整条件仍需确认。"
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
    description="本地证据检索，不发送资料到外部；固定快照和修订，引用不存在返回 404，不一致返回 422。",
    response_model=ApiResponse[MatchRead],
    status_code=201,
)
async def create_match(session: SessionDep, payload: MatchCreate) -> ApiResponse[MatchRead]:
    """验证输入后保存不可变证据报告，无外部调用。"""
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
    return success([MatchRead.model_validate(row) for row in rows])
