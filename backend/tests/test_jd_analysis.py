"""可信条件分析回归；API 写入仅由 db_client 随机 schema 隔离。"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.errors import ValidationFailedError
from app.modules.job.analysis import parse_jd
from app.modules.job.exclusions import EvaluationInput, ExclusionRule, evaluate
from app.modules.matching.scoring import (
    Assessments,
    Condition,
    apply_assessments,
    conditions,
    employment_ratio,
    location_ratio,
    score,
    strategy_conditions,
)


def test_known_city_and_employment_aliases_do_not_make_false_hard_conflicts() -> None:
    """同源城市目录和明确雇佣同义词可对应，未知地址与自由类型不猜。"""
    assert location_ratio("南京", ["江苏省南京市"]) == 1
    assert location_ratio("上海市", ["北京", "上海"]) == 1
    assert location_ratio("杭州", ["北京", "上海"]) == 0
    assert location_ratio("某园区", ["上海"]) is None
    assert employment_ratio("FULL_TIME", ["全职"]) == 1
    assert employment_ratio("其他自由类型", ["全职"]) is None


def test_unknown_bounds_and_hard_gate() -> None:
    """未知仍有可能上界，覆盖达标也不能越过硬条件未知或冲突。"""
    rows = [
        Condition(id="skills", dimension="SKILL", text="技能", status="KNOWN", ratio=1),
        Condition(id="salary", dimension="SALARY", text="薪资", hard=True),
    ]
    result = score(rows)
    assert result["lower"] == pytest.approx(20 / 3)
    assert result["upper"] == pytest.approx(10)
    assert result["single_score"] is None
    assert result["recommendation"] == "先补充/确认信息"
    assert score([rows[0]], excluded=True)["recommendation"] == "不建议投递"
    assert score([])["single_score"] is None


def test_not_applicable_and_deduplication() -> None:
    """福利不评分，重复摘录不增加条件权重；准入维度不适用可归一。"""
    rows = conditions(parse_jd("熟悉 Python\n熟悉 Python\n福利：五险一金"))
    assert len([row for row in rows if row.dimension == "SKILL"]) == 1
    assert any(row.dimension == "ADMISSION" and row.status == "UNKNOWN" for row in rows)
    assert sum(row["weight"] for row in score(rows)["conditions"]) == pytest.approx(10)


@pytest.mark.parametrize(
    "currency,period,basis,low,high,expected",
    [
        ("CNY", "MONTH", "GROSS", 12000, 16000, None),
        ("CNY", "MONTH", "GROSS", 16000, 20000, 1),
        ("CNY", "MONTH", "GROSS", 8000, 12000, 0),
        ("USD", "MONTH", "GROSS", 16000, 20000, None),
        ("CNY", "YEAR", "GROSS", 16000, 20000, None),
        ("CNY", "MONTH", "NET", 16000, 20000, None),
    ],
)
def test_salary_interval_and_basis(
    currency: str, period: str, basis: str, low: int, high: int, expected: float | None
) -> None:
    """跨底线和不同币种/周期/税口径保持未知；只有明确上界低于底线冲突。"""
    pref = {
        "preference": {
            "salary_min": 15000,
            "salary_currency": "CNY",
            "hard_limits": {"salary": True, "salary_basis": "GROSS"},
        }
    }
    rows, conflicts, unknowns = strategy_conditions(
        [], pref, {"salary": {"min": low, "max": high, "currency": currency, "period": period, "basis": basis}}, ""
    )
    assert next(row for row in rows if row.id == "strategy-salary_floor").ratio == expected
    assert bool(conflicts) == (expected == 0)
    assert bool(unknowns) == (expected is None)


@pytest.mark.parametrize(
    "term,jd,verdict",
    [
        ("Java", "JavaScript", "ELIGIBLE"),
        ("C++", "C#", "ELIGIBLE"),
        ("C", "C++", "ELIGIBLE"),
        ("C#", "熟悉 C#", "EXCLUDED"),
        ("外包", "非外包", "REVIEW"),
        ("Java", "不要求 Java", "REVIEW"),
        ("Node.js", "Node.jsx", "ELIGIBLE"),
    ],
)
def test_safe_keyword_boundaries(term: str, jd: str, verdict: str) -> None:
    """英文、符号技能和否定不能产生错误的确定排除。"""
    result = evaluate(
        [ExclusionRule(id="r", kind="JD_KEYWORD", value=term)],
        EvaluationInput(company_name="", nature_code=None, industry_code=None, outsourcing_arrangement=None, raw_jd=jd),
    )
    assert result.verdict == verdict


def test_model_quote_scope_and_anchor() -> None:
    """伪造事实/摘录拒绝；名称对应上限保守且不能提升为能力核实。"""
    row = Condition(id="c1", dimension="SKILL", text="Python")
    output = Assessments.model_validate(
        {
            "assessments": [
                {
                    "condition_id": "c1",
                    "ratio": 1,
                    "fact_ids": ["s"],
                    "fact_quotes": ["Python"],
                    "explanation": "名称对应",
                }
            ]
        }
    )
    assert apply_assessments([row], output, {"s": {"id": "s", "name": "Python"}})[0].ratio == 0.25
    with pytest.raises(ValidationFailedError):
        apply_assessments([row], output, {"other": {"name": "Python"}})
    with pytest.raises(ValidationError):
        Condition(id="c", dimension="SKILL", text="技能", status="KNOWN", ratio=0.7)


def test_jd_only_without_profile_and_independent_parse(db_client: TestClient) -> None:
    """无档案、公司、标题、链接仍能保存和解析，空白/超长拒绝。"""
    saved = db_client.post("/api/v1/jobs", json={"raw_jd": "熟悉 Python"})
    assert saved.status_code == 201, saved.text
    data = saved.json()["data"]
    assert data["company"] is None and data["title"] is None
    assert db_client.get("/api/v1/jobs").json()["data"][0]["company_name"] is None
    assert db_client.get(f"/api/v1/jobs/{data['id']}/exclusion").status_code == 200
    assert db_client.post(f"/api/v1/job-snapshots/{data['latest_snapshot']['id']}/parses", json={}).status_code == 201
    for raw in ("  ", "a" * 100001):
        assert db_client.post("/api/v1/jobs", json={"raw_jd": raw}).status_code == 422


def test_new_analysis_frozen_idempotent_and_stale(db_client: TestClient) -> None:
    """新报告固定解析/策略；重复调用复用，偏好变化历史保持原样且标过期。"""
    db_client.post("/api/v1/profile", json={"full_name": "测试"})
    db_client.post("/api/v1/profile/skills", json={"name": "Python"})
    revision = db_client.post("/api/v1/profile/revisions", json={"reason": "分析"}).json()["data"]
    preference = db_client.put("/api/v1/profile/preference", json={"target_roles": ["开发"]})
    assert preference.status_code == 200, preference.text
    job = db_client.post("/api/v1/jobs", json={"raw_jd": "熟悉 Python\n负责开发"}).json()["data"]
    snapshot = job["latest_snapshot"]["id"]
    parsed = db_client.post(f"/api/v1/job-snapshots/{snapshot}/parses", json={}).json()["data"]
    payload = {"job_snapshot_id": snapshot, "profile_revision_id": revision["id"], "parse_result_id": parsed["id"]}
    report = db_client.post("/api/v1/matches", json=payload)
    assert report.status_code == 201, report.text
    data = report.json()["data"]
    assert data["report_json"]["reference_score"]["single_score"] is None
    assert db_client.post("/api/v1/matches", json=payload).json()["data"]["id"] == data["id"]
    assert db_client.get("/api/v1/matches").json()["data"][0]["is_stale"] is False
    db_client.put(
        "/api/v1/profile/preference", json={"version": preference.json()["data"]["version"], "target_roles": ["测试"]}
    )
    history = db_client.get("/api/v1/matches").json()["data"][0]
    assert history["is_stale"] is True
    assert history["report_json"] == data["report_json"]
    other = db_client.post("/api/v1/jobs", json={"raw_jd": "其他 JD"}).json()["data"]
    assert (
        db_client.post(
            "/api/v1/matches", json={**payload, "job_snapshot_id": other["latest_snapshot"]["id"]}
        ).status_code
        == 422
    )
    assert db_client.post("/api/v1/matches", json={**payload, "parse_result_id": str(uuid4())}).status_code == 404
    assert db_client.post("/api/v1/matches", json={**payload, "engine": "AI"}).status_code == 422
