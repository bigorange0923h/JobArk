"""JD 可靠性缺口的最小复现；不读取或修改真实资料。"""

import pytest
from fastapi.testclient import TestClient

from app.modules.job.analysis import JDAnalysis, parse_jd, validate_source
from app.modules.matching.readiness import data_warnings, fact_evidence
from app.modules.matching.scoring import conditions, strategy_conditions


def test_mixed_line_preserves_independent_admission_and_offsets() -> None:
    """同句要求不能因含开发一词丢掉学历和经验。"""
    raw = "任职要求：\n熟悉 Python 开发，至少 3 年经验，本科及以上学历"
    parsed = parse_jd(raw)
    assert {row.category for row in parsed.requirements} == {"SKILL", "EXPERIENCE", "EDUCATION"}
    assert all(raw[row.source_start : row.source_end] == row.source_quote for row in parsed.requirements)
    assert next(row for row in parsed.requirements if row.category == "EXPERIENCE").experience_subject is None
    assert parse_jd("至少 3 年 Python 开发经验").requirements[0].experience_subject == "Python"
    assert any(row.dimension == "ADMISSION" and row.status == "UNKNOWN" for row in conditions(parsed))


def test_missing_admission_is_not_proof_of_not_applicable() -> None:
    """未识别不能当作明确不存在；明确不设准入才不适用。"""
    assert all(row.status != "NOT_APPLICABLE" for row in conditions(parse_jd("熟悉 Python")))
    assert any(row.status == "NOT_APPLICABLE" for row in conditions(parse_jd("无准入要求")))


def test_or_qualifications_remain_one_alternative_group() -> None:
    """学历与经验替代关系不能误拆为必须同时满足。"""
    parsed = parse_jd("本科或至少 5 年相关经验")
    assert len(parsed.requirements) == 1
    assert parsed.requirements[0].relation == "OR"
    assert not parsed.requirements[0].hard


def test_direction_uses_title_and_keeps_keyword_clues_separate() -> None:
    """标题是方向线索，关键词不能代替方向意愿。"""
    rows, _, _ = strategy_conditions(
        [],
        {"preference": {"target_roles": ["AI应用开发"], "role_keywords": ["RAG"]}},
        {"title": "AI应用开发工程师"},
        "负责企业知识库与 Agent 开发",
    )
    direction = next(row for row in rows if row.dimension == "DIRECTION")
    assert direction.ratio == 0.75


def test_acceptable_floor_differs_from_target_and_no_ceiling_penalty() -> None:
    """期望区间与底线分离，高于期望上界不构成不适合。"""
    pref = {
        "preference": {
            "salary_min": 25000,
            "salary_max": 35000,
            "acceptable_salary_min": 20000,
            "salary_currency": "CNY",
            "hard_limits": {"salary": True, "salary_basis": "GROSS"},
        }
    }

    def evaluate(low: int, high: int):
        """使用明确月薪税前区间构造本地比较。"""
        return strategy_conditions(
            [], pref, {"salary": {"min": low, "max": high, "currency": "CNY", "period": "MONTH", "basis": "GROSS"}}, ""
        )

    rows, conflicts, unknowns = evaluate(22000, 24000)
    assert not conflicts and not unknowns
    assert next(row for row in rows if row.id == "strategy-salary").ratio == 0.5
    assert evaluate(15000, 19000)[1]
    assert evaluate(19000, 23000)[2]
    assert next(row for row in evaluate(40000, 45000)[0] if row.id == "strategy-salary").ratio == 1


def test_quote_offsets_and_false_admission_exemption_are_rejected() -> None:
    """位置不能来自其他片段；没有提取到准入也不能声明无准入。"""
    parsed = parse_jd("熟悉 Python")
    validate_source(parsed, "熟悉 Python")
    parsed.requirements[0].source_start = 1
    with pytest.raises(ValueError, match="位置"):
        validate_source(parsed, "熟悉 Python")
    with pytest.raises(ValueError, match="准入"):
        validate_source(JDAnalysis(requirements=[], uncertainties=[], admission_status="NONE"), "本科及以上")


def test_floor_only_salary_requires_confirmed_tax_basis() -> None:
    """仅设置底线也要确认比较口径，明确口径后不再提示。"""
    preference = {"acceptable_salary_min": 0}
    assert any("税前/税后" in warning for warning in data_warnings({}, preference))
    assert not any(
        "税前/税后" in warning
        for warning in data_warnings({}, {**preference, "hard_limits": {"salary_basis": "GROSS"}})
    )
    assert not any("税前/税后" in warning for warning in data_warnings({}, {}))


def test_source_attachment_is_not_full_claim_support() -> None:
    """来源只覆盖具体摘录；本人陈述不会因摘录相同自动变独立证明。"""
    fact = {"name": "项目", "source_evidence_id": "e"}
    sources = {"e": {"title": "简历摘录", "content": "项目 核心开发", "source_type": "RESUME_DOCUMENT"}}
    assert fact_evidence("f", fact, "核心开发", sources)["source_support"] == "EXCERPT_SUPPORTED"
    assert fact_evidence("f", fact, "吞吐提升 50%", sources)["source_support"] == "SOURCE_ATTACHED"
    sources["e"]["source_type"] = "MANUAL_DECLARATION"
    assert fact_evidence("f", fact, "核心开发", sources)["source_support"] == "SELF_DECLARED"


def test_new_education_and_strategy_contracts(db_client: TestClient) -> None:
    """隔离 API 验证保存、合法输入、清空、冲突、缺资源与修订字段。"""
    from uuid import uuid4

    assert db_client.post("/api/v1/profile", json={"full_name": "测试"}).status_code == 201
    payload = {
        "school": "测试学校",
        "degree": "本科（非全日制）",
        "degree_level": "BACHELOR",
        "study_mode": "PART_TIME",
    }
    response = db_client.post("/api/v1/profile/educations", json=payload)
    assert response.status_code == 201, response.text
    row = response.json()["data"]
    invalid = db_client.post("/api/v1/profile/educations", json={**payload, "study_mode": "GUESSED"})
    assert invalid.status_code == 422
    assert (
        db_client.patch(f"/api/v1/profile/educations/{uuid4()}", json={"version": 1, "study_mode": None}).status_code
        == 404
    )
    changed = db_client.patch(
        f"/api/v1/profile/educations/{row['id']}", json={"version": row["version"], "study_mode": None}
    )
    assert changed.status_code == 200 and changed.json()["data"]["study_mode"] is None
    assert (
        db_client.patch(
            f"/api/v1/profile/educations/{row['id']}", json={"version": row["version"], "study_mode": "FULL_TIME"}
        ).status_code
        == 409
    )
    revision = db_client.post("/api/v1/profile/revisions", json={"reason": "分析"}).json()["data"]
    assert revision["snapshot_json"]["educations"][0]["degree_level"] == "BACHELOR"
    assert revision["snapshot_json"]["educations"][0]["degree"] == payload["degree"]
    pref = {
        "target_roles": ["AI应用开发"],
        "role_keywords": ["RAG"],
        "salary_min": 25000,
        "salary_max": 35000,
        "acceptable_salary_min": 20000,
        "salary_currency": "CNY",
        "hard_limits": {"salary": True, "salary_basis": "GROSS"},
    }
    saved = db_client.put("/api/v1/profile/preference", json=pref)
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["role_keywords"] == ["RAG"]
    assert (
        db_client.put(
            "/api/v1/profile/preference", json={**pref, "acceptable_salary_min": 30000, "version": 1}
        ).status_code
        == 422
    )
    assert (
        db_client.put(
            "/api/v1/profile/preference",
            json={"hard_limits": {"remote": True}, "remote_preference": "ANY", "version": 1},
        ).status_code
        == 422
    )
