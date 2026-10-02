"""已确认数据模型边界的回归测试；纯快照测试不连接或清理业务数据库。"""

import uuid
from datetime import UTC, date, datetime

from app.modules.profile.enums import EvidenceSourceType, VerificationStatus
from app.modules.profile.models import PersonalProfile, ProfileEducation, ProfileEvidence, ProfileProject
from app.modules.profile.service import build_profile_snapshot


def test_revision_freezes_project_dates_and_source_content() -> None:
    """修订保存项目时间与来源原文；当前来源编辑不能回写历史内容。"""
    evidence = ProfileEvidence(
        id=uuid.uuid4(),
        version=1,
        source_type=EvidenceSourceType.PROJECT_LINK,
        title="项目来源",
        content="已确认的项目摘录",
        source_hash="source-hash",
        verification_status=VerificationStatus.UNVERIFIED,
    )
    project = ProfileProject(
        id=uuid.uuid4(),
        name="项目",
        tech_stack=["Python"],
        source_evidence_id=evidence.id,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 6, 1),
    )
    profile = PersonalProfile(
        id=uuid.uuid4(),
        full_name="测试",
        links=[],
        evidences=[evidence],
        projects=[project],
        educations=[],
        experiences=[],
        skills=[],
        languages=[],
    )
    snapshot = build_profile_snapshot(profile)
    evidence.content = "后来改写的内容"
    assert snapshot["schema_version"] == 2
    assert snapshot["projects"][0]["start_date"] == "2024-01-01"
    assert snapshot["projects"][0]["end_date"] == "2024-06-01"
    assert snapshot["projects"][0]["experience_id"] is None
    assert snapshot["evidences"][0]["content"] == "已确认的项目摘录"


def test_revision_excludes_archived_facts_even_when_relationship_is_loaded() -> None:
    """内存聚合含归档条目时，新修订也不能重新引入它。"""
    education = ProfileEducation(id=uuid.uuid4(), school="旧学校", archived_at=datetime.now(UTC))
    profile = PersonalProfile(
        id=uuid.uuid4(),
        full_name="测试",
        links=[],
        educations=[education],
        evidences=[],
        projects=[],
        experiences=[],
        skills=[],
        languages=[],
    )
    assert build_profile_snapshot(profile)["educations"] == []
