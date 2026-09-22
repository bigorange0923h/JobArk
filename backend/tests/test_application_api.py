"""申请状态、不可变引用与统计复算的集成验证。"""

from typing import Any

from fastapi.testclient import TestClient


def application_payload(client: TestClient) -> dict[str, Any]:
    """通过公开接口创建最小职位、资料修订和简历版本。"""
    assert client.post("/api/v1/profile", json={"full_name": "测试候选人"}).status_code == 201
    revision = client.post("/api/v1/profile/revisions", json={"reason": "测试"}).json()["data"]
    resume = client.post("/api/v1/resumes", json={"name": "测试简历"}).json()["data"]
    version_response = client.post(
        f"/api/v1/resumes/{resume['id']}/versions",
        json={
            "profile_revision_id": revision["id"],
            "document": {"basics": {"full_name": "测试候选人"}},
            "created_reason": "测试",
        },
    )
    assert version_response.status_code == 201, version_response.text
    job = client.post(
        "/api/v1/jobs", json={"company": {"name": "测试公司"}, "title": "测试职位", "raw_jd": "测试 JD"}
    ).json()["data"]
    return {
        "job_opportunity_id": job["id"],
        "job_snapshot_id": job["latest_snapshot"]["id"],
        "resume_version_id": version_response.json()["data"]["id"],
    }


def test_application_transitions_and_dashboard(db_client: TestClient) -> None:
    """确认、合法边、版本检查及统计必须与事件一致。"""
    payload = application_payload(db_client)
    created = db_client.post("/api/v1/applications", json=payload)
    assert created.status_code == 201, created.text
    app = created.json()["data"]
    path = f"/api/v1/applications/{app['id']}/events"
    assert db_client.post(path, json={"version": 1, "status": "OFFERED"}).status_code == 409
    assert db_client.post(path, json={"version": 1, "status": "APPLIED"}).status_code == 422
    applied = db_client.post(path, json={"version": 1, "status": "APPLIED", "confirm_applied": True})
    assert applied.status_code == 200, applied.text
    assert len(applied.json()["data"]["events"]) == 2
    assert db_client.post(path, json={"version": 1, "status": "INTERVIEWING"}).status_code == 409
    interview = db_client.post(path, json={"version": 2, "status": "INTERVIEWING"})
    assert interview.status_code == 200
    assert len(interview.json()["data"]["events"]) == 3
    dashboard = db_client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    stats = dashboard.json()["data"]
    assert stats["application_count"] == 1
    assert stats["pending_jobs"] == 0
    assert stats["versions"][0]["interviewed"] == 1
    assert stats["versions"][0]["applied"] == 1


def test_repeat_requires_confirmation_and_keeps_previous(db_client: TestClient) -> None:
    """重复申请产生新尝试，旧快照引用和事件完整保留。"""
    payload = application_payload(db_client)
    first = db_client.post("/api/v1/applications", json=payload).json()["data"]
    assert db_client.post("/api/v1/applications", json=payload).status_code == 409
    repeated = db_client.post("/api/v1/applications", json={**payload, "confirm_repeat": True})
    assert repeated.status_code == 201
    assert repeated.json()["data"]["attempt_no"] == 2
    assert repeated.json()["data"]["id"] != first["id"]
    assert len(db_client.get(f"/api/v1/applications/{first['id']}").json()["data"]["events"]) == 1


def test_wrong_snapshot_and_missing_references_do_not_create_application(db_client: TestClient) -> None:
    """错误引用不能创建申请或初始事件；空统计不虚构数据。"""
    payload = application_payload(db_client)
    other = db_client.post(
        "/api/v1/jobs",
        json={
            "company": {"name": "另一公司"},
            "title": "其他职位",
            "raw_jd": "其他 JD",
        },
    ).json()["data"]
    assert (
        db_client.post(
            "/api/v1/applications",
            json={
                **payload,
                "job_snapshot_id": other["latest_snapshot"]["id"],
            },
        ).status_code
        == 422
    )
    assert (
        db_client.post(
            "/api/v1/applications",
            json={
                **payload,
                "resume_version_id": other["id"],
            },
        ).status_code
        == 404
    )
    assert db_client.get(f"/api/v1/applications/{other['id']}").status_code == 404
    assert db_client.get("/api/v1/applications").json()["data"] == []
    stats = db_client.get("/api/v1/dashboard").json()["data"]
    assert stats["application_count"] == 0
    assert stats["pending_jobs"] == 2
