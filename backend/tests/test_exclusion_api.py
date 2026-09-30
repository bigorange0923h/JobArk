"""结构化策略与单职位例外的数据库接口验收。"""

from typing import Any

from fastapi.testclient import TestClient


def create_job(client: TestClient, name: str = "同名公司", jd: str = "普通直招岗位") -> dict[str, Any]:
    """创建独立公司与机会，避免同名自动合并。"""
    response = client.post(
        "/api/v1/jobs",
        json={
            "company": {"name": name, "website_url": None, "industry": "旧行业自由文本", "location": None},
            "title": "工程师",
            "raw_jd": jd,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_policy_legacy_and_exception_lifecycle(db_client: TestClient) -> None:
    """旧行业不自动分类，例外需确认且规则版本变化后失效。"""
    job = create_job(db_client)
    job_id = job["id"]
    policy = db_client.put(
        "/api/v1/exclusion-policy",
        json={
            "version": 0,
            "rules": [{"id": "r1", "kind": "COMPANY_INDUSTRY", "value": "TECH", "enabled": True}],
        },
    )
    assert policy.status_code == 200
    preview = db_client.get(f"/api/v1/jobs/{job_id}/exclusion")
    assert preview.json()["data"]["decision"]["verdict"] == "REVIEW"
    before = preview.json()["data"]
    denied = db_client.post(
        f"/api/v1/jobs/{job_id}/exclusion/exception",
        json={
            "snapshot_id": before["snapshot_id"],
            "policy_version": before["policy_version"],
            "company_version": before["company_version"],
            "opportunity_version": before["opportunity_version"],
            "reason": "已人工核对",
            "confirm": False,
        },
    )
    assert denied.status_code == 422
    assert db_client.get(f"/api/v1/jobs/{job_id}/exclusion").json()["data"]["exception_active"] is False
    granted = db_client.post(
        f"/api/v1/jobs/{job_id}/exclusion/exception",
        json={
            "snapshot_id": before["snapshot_id"],
            "policy_version": before["policy_version"],
            "company_version": before["company_version"],
            "opportunity_version": before["opportunity_version"],
            "reason": "已人工核对本岗位",
            "confirm": True,
        },
    )
    assert granted.status_code == 200
    assert granted.json()["data"]["preparation_allowed"] is True
    updated = db_client.put("/api/v1/exclusion-policy", json={"version": 1, "rules": []})
    assert updated.status_code == 200
    assert db_client.get(f"/api/v1/jobs/{job_id}/exclusion").json()["data"]["exception_active"] is False


def test_confirmed_job_arrangement_does_not_change_company_nature(db_client: TestClient) -> None:
    """单岗位外包安排命中，其它同名职位不因这个岗位被排除。"""
    first = create_job(db_client)
    second = create_job(db_client)
    assert (
        db_client.put(
            "/api/v1/exclusion-policy",
            json={
                "version": 0,
                "rules": [
                    {"id": "outsourcing", "kind": "COMPANY_NATURE", "value": "OUTSOURCING_RELATED", "enabled": True}
                ],
            },
        ).status_code
        == 200
    )
    confirm = db_client.patch(
        f"/api/v1/jobs/{first['id']}/exclusion-facts",
        json={
            "company_version": first["company"]["version"],
            "opportunity_version": first["version"],
            "nature_code": "OTHER",
            "outsourcing_arrangement": "OUTSOURCING",
            "confirm": True,
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["data"]["decision"]["verdict"] == "EXCLUDED"
    assert db_client.get(f"/api/v1/jobs/{second['id']}/exclusion").json()["data"]["decision"]["verdict"] == "REVIEW"


def test_exception_invalidates_after_jd_or_company_change(db_client: TestClient) -> None:
    """例外绑定当前快照和公司版本，任一输入变化后不再放行。"""
    job = create_job(db_client)
    job_id = job["id"]
    assert (
        db_client.put(
            "/api/v1/exclusion-policy",
            json={
                "version": 0,
                "rules": [{"id": "name", "kind": "COMPANY_NAME", "value": "同名公司", "enabled": True}],
            },
        ).status_code
        == 200
    )

    def grant() -> None:
        """仅为当前输入记录一条例外。"""
        current = db_client.get(f"/api/v1/jobs/{job_id}/exclusion").json()["data"]
        response = db_client.post(
            f"/api/v1/jobs/{job_id}/exclusion/exception",
            json={
                "snapshot_id": current["snapshot_id"],
                "policy_version": current["policy_version"],
                "company_version": current["company_version"],
                "opportunity_version": current["opportunity_version"],
                "reason": "人工核对后的单次例外",
                "confirm": True,
            },
        )
        assert response.status_code == 200
        assert response.json()["data"]["exception_active"] is True

    grant()
    posting = job["postings"][0]["id"]
    assert (
        db_client.post(
            f"/api/v1/jobs/{job_id}/postings/{posting}/snapshots",
            json={
                "raw_jd": "更新后的 JD",
            },
        ).status_code
        == 201
    )
    assert db_client.get(f"/api/v1/jobs/{job_id}/exclusion").json()["data"]["exception_active"] is False
    grant()
    detail = db_client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert (
        db_client.patch(
            f"/api/v1/jobs/{job_id}/exclusion-facts",
            json={
                "company_version": detail["company"]["version"],
                "opportunity_version": detail["version"],
                "nature_code": "OTHER",
                "confirm": True,
            },
        ).status_code
        == 200
    )
    assert db_client.get(f"/api/v1/jobs/{job_id}/exclusion").json()["data"]["exception_active"] is False
