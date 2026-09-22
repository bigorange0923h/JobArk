"""证据匹配不把未知当失败，不虚构技能或总分。"""

from fastapi.testclient import TestClient

from app.modules.job.analysis import parse_jd
from app.modules.matching.router import build_report


def test_parser_retains_quotes_and_unknown_conditions() -> None:
    """未知条件保持未知，引用必须逐字出现在原文。"""
    jd = "必须掌握 Python\n五年以上经验\n弹性工作"
    result = parse_jd(jd)
    assert all(item.source_quote in jd for item in result.requirements)
    assert result.requirements[0].hard
    assert result.requirements[2].category == "UNKNOWN"


def test_evidence_does_not_imply_satisfying_full_requirement() -> None:
    """技能出现不代表满足年限；简历匹配要求实际表达该资料事实。"""
    profile = {"skills": [{"id": "skill-1", "name": "Python", "claim_status": "UNVERIFIED"}]}
    report = build_report("必须熟悉 Python 并有五年经验", profile, None)
    assert report["overall_score"] is None
    assert report["requirements"][0]["status"] == "EVIDENCE_FOUND"
    assert report["requirements"][0]["evidence"][0]["claim_status"] == "UNVERIFIED"
    missing = build_report("必须熟悉 Python", profile, {"skills": []})
    assert missing["requirements"][0]["status"] == "UNKNOWN"


def test_skill_names_do_not_match_longer_identifiers() -> None:
    """相似英文名称不代表相同技能，标点结尾技能也必须完整匹配。"""
    profile = {"skills": [{"id": "s1", "name": "Java"}, {"id": "s2", "name": "C"}]}
    result = build_report("熟悉 JavaScript 和 C++", profile, None)
    assert result["requirements"][0]["status"] == "UNKNOWN"
    assert build_report("熟悉Java、C语言", profile, None)["requirements"][0]["status"] == "EVIDENCE_FOUND"


def test_matching_inputs_and_history(db_client: TestClient) -> None:
    """历史绑定固定输入；缺引用及不一致的简历修订不得落库。"""
    db_client.post("/api/v1/profile", json={"full_name": "测试"})
    revision = db_client.post("/api/v1/profile/revisions", json={"reason": "匹配基线"}).json()["data"]
    resume = db_client.post("/api/v1/resumes", json={"name": "测试"}).json()["data"]
    version = db_client.post(
        f"/api/v1/resumes/{resume['id']}/versions",
        json={
            "profile_revision_id": revision["id"],
            "document": {"basics": {"full_name": "测试"}},
            "created_reason": "测试",
        },
    ).json()["data"]
    job = db_client.post(
        "/api/v1/jobs",
        json={
            "company": {"name": "测试"},
            "title": "开发",
            "raw_jd": "必须熟悉 Python",
        },
    ).json()["data"]
    payload = {"job_snapshot_id": job["latest_snapshot"]["id"], "profile_revision_id": revision["id"]}
    first = db_client.post("/api/v1/matches", json=payload)
    assert first.status_code == 201
    assert first.json()["data"]["match_kind"] == "PROFILE"
    second = db_client.post("/api/v1/matches", json={**payload, "resume_version_id": version["id"]})
    assert second.status_code == 201
    assert second.json()["data"]["match_kind"] == "RESUME"
    assert db_client.post("/api/v1/matches", json={**payload, "profile_revision_id": job["id"]}).status_code == 404
    other = db_client.post("/api/v1/profile/revisions", json={"reason": "其他修订"}).json()["data"]
    assert (
        db_client.post(
            "/api/v1/matches",
            json={
                **payload,
                "resume_version_id": version["id"],
                "profile_revision_id": other["id"],
            },
        ).status_code
        == 422
    )
    history = db_client.get("/api/v1/matches").json()["data"]
    assert len(history) == 2
    assert {item["input_fingerprint"] for item in history} == {
        first.json()["data"]["input_fingerprint"],
        second.json()["data"]["input_fingerprint"],
    }
