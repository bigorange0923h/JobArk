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
    # 没有来源记录的技能同样是命中，但状态点名"命中事实"而不是"找到证据"。
    assert report["requirements"][0]["status"] == "FACT_FOUND"
    assert report["requirements"][0]["evidence"][0]["claim_status"] == "UNVERIFIED"
    assert report["requirements"][0]["evidence"][0]["evidence_id"] is None
    missing = build_report("必须熟悉 Python", profile, {"skills": []})
    assert missing["requirements"][0]["status"] == "UNKNOWN"


def test_status_distinguishes_literal_fact_from_attached_source() -> None:
    """命中状态必须区分"字面命中"与"另挂来源记录"，且都不暗示已核实。"""
    bare = {"skills": [{"id": "skill-1", "name": "Python", "claim_status": "UNVERIFIED"}]}
    sourced = {
        "skills": [
            {
                "id": "skill-1",
                "name": "Python",
                "claim_status": "UNVERIFIED",
                "source_evidence_id": "evidence-1",
            }
        ],
        "evidences": [{"id": "evidence-1", "title": "导入简历：sample.html"}],
    }

    bare_row = build_report("必须熟悉 Python", bare, None)["requirements"][0]
    assert bare_row["status"] == "FACT_FOUND"
    assert bare_row["evidence"][0]["evidence_title"] == ""
    # 文案明确这是名称层面的字面匹配，不暗示能力或整项条件已核实。
    assert "字面匹配" in bare_row["explanation"]
    assert "不代表能力" in bare_row["explanation"]

    sourced_row = build_report("必须熟悉 Python", sourced, None)["requirements"][0]
    assert sourced_row["status"] == "EVIDENCE_ATTACHED"
    assert sourced_row["evidence"][0]["evidence_title"] == "导入简历：sample.html"
    assert sourced_row["evidence"][0]["claim_status"] == "UNVERIFIED"


def test_skill_names_do_not_match_longer_identifiers() -> None:
    """相似英文名称不代表相同技能，标点结尾技能也必须完整匹配。"""
    profile = {"skills": [{"id": "s1", "name": "Java"}, {"id": "s2", "name": "C"}]}
    result = build_report("熟悉 JavaScript 和 C++", profile, None)
    assert result["requirements"][0]["status"] == "UNKNOWN"
    assert build_report("熟悉Java、C语言", profile, None)["requirements"][0]["status"] == "FACT_FOUND"


def test_manual_skill_without_evidence_is_usable(db_client: TestClient) -> None:
    """手工填写、没有任何来源证据的技能可以保存，并可用于匹配与简历候选。"""
    db_client.post("/api/v1/profile", json={"full_name": "测试"})
    created = db_client.post("/api/v1/profile/skills", json={"name": "Python"})
    assert created.status_code == 201, created.text
    skill = created.json()["data"]
    assert skill["source_evidence_id"] is None
    assert skill["claim_status"] == "UNVERIFIED"

    revision = db_client.post("/api/v1/profile/revisions", json={"reason": "匹配基线"}).json()["data"]
    job = db_client.post(
        "/api/v1/jobs",
        json={"company": {"name": "测试"}, "title": "开发", "raw_jd": "必须熟悉 Python"},
    ).json()["data"]
    match = db_client.post(
        "/api/v1/matches",
        json={"job_snapshot_id": job["latest_snapshot"]["id"], "profile_revision_id": revision["id"]},
    )

    assert match.status_code == 201, match.text
    row = match.json()["data"]["report_json"]["requirements"][0]
    assert row["status"] == "FACT_FOUND"
    assert row["evidence"][0]["claim_status"] == "UNVERIFIED"
    assert row["evidence"][0]["evidence_id"] is None

    # 同一份无来源事实也能进入简历版本：不要求先补证据就能用。
    resume = db_client.post("/api/v1/resumes", json={"name": "测试"}).json()["data"]
    version = db_client.post(
        f"/api/v1/resumes/{resume['id']}/versions",
        json={
            "profile_revision_id": revision["id"],
            "document": {
                "basics": {"full_name": "测试"},
                "skills": [{"name": "Python", "source_fact_id": skill["id"]}],
            },
            "created_reason": "测试",
        },
    )
    assert version.status_code == 201, version.text

    # 但"无证据"不能被说成"已核实"：标为已验证仍然被拒绝。
    verified = db_client.patch(
        f"/api/v1/profile/skills/{skill['id']}",
        json={"version": skill["version"], "claim_status": "VERIFIED"},
    )
    assert verified.status_code == 422


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
