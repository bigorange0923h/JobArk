"""职位输入和冲突回归，防止接口将预期业务错误变成 500。"""

from fastapi.testclient import TestClient


def test_duplicate_url_returns_conflict(db_client: TestClient) -> None:
    """同一 URL 重复录入返回 409，失败事务不能遗留机会。"""
    payload = {
        "company": {"name": "测试"},
        "title": "测试职位",
        "raw_jd": "测试内容",
        "canonical_url": "https://example.com/job",
    }
    assert db_client.post("/api/v1/jobs", json=payload).status_code == 201
    assert db_client.post("/api/v1/jobs", json=payload).status_code == 409
    assert len(db_client.get("/api/v1/jobs").json()["data"]) == 1


def test_blank_input_and_nullable_patch(db_client: TestClient) -> None:
    """纯空白标题拒绝，显式 null 可清空备注。"""
    payload = {"company": {"name": "测试"}, "title": "  ", "raw_jd": "测试内容"}
    assert db_client.post("/api/v1/jobs", json=payload).status_code == 422
    payload["title"] = "测试职位"
    result = db_client.post("/api/v1/jobs", json={**payload, "notes": "待清空"}).json()["data"]
    response = db_client.patch(f"/api/v1/jobs/{result['id']}", json={"version": 1, "notes": None})
    assert response.status_code == 200
    assert response.json()["data"]["notes"] is None
