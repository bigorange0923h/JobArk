"""可选 AI 功能与默认模型的确认、失败与输出边界；不调用真实外部服务。"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.llm import gateway

AI_API = "/api/v1/ai"


def _configure_default_model(client: TestClient) -> None:
    """创建服务商与首个模型，使唯一默认模型存在。

    刻意不提交 API Key：本文件验证的是调用契约与确认边界，不需要凭据，
    因此也不依赖 TEST 环境的凭据加密根密钥。
    """
    provider = client.post(
        f"{AI_API}/providers",
        json={"name": "测试服务商", "base_url": "https://example.test/v1"},
    ).json()["data"]
    created = client.post(
        f"{AI_API}/providers/{provider['id']}/models",
        json={"name": "测试模型", "remote_model_id": "test-model"},
    )
    assert created.status_code == 201, created.text


def test_jd_failure_keeps_original(db_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """模型伪造原文引用时保存失败产物，原始 JD 不变。"""
    _configure_default_model(db_client)

    async def fake(
        config: gateway.ResolvedAiModel, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """模拟结构有效但引用不存在的模型响应。"""
        return {
            "requirements": [{"text": "博士", "source_quote": "博士", "hard": True, "category": "EDUCATION"}],
            "uncertainties": [],
        }

    monkeypatch.setattr(gateway, "generate", fake)
    job = db_client.post(
        "/api/v1/jobs", json={"company": {"name": "测试公司"}, "title": "测试", "raw_jd": "熟悉 Python"}
    ).json()["data"]
    url = f"/api/v1/job-snapshots/{job['latest_snapshot']['id']}/parses"
    assert db_client.post(url, json={"engine": "AI", "confirm_external": False}).status_code == 422
    result = db_client.post(url, json={"engine": "AI", "confirm_external": True})
    assert result.status_code == 201
    assert result.json()["data"]["status"] == "FAILED"
    assert result.json()["data"]["result_json"] is None
    assert db_client.get(f"/api/v1/jobs/{job['id']}").json()["data"]["latest_snapshot"]["raw_jd"] == "熟悉 Python"
    local = db_client.post(url, json={"engine": "LOCAL"})
    assert local.json()["data"]["status"] == "PARSED"
    assert len(db_client.get(url).json()["data"]) == 2


def test_ai_flow_without_default_model_fails_safely(db_client: TestClient) -> None:
    """没有默认模型时 AI 功能返回 409，并提示前往 AI 模型配置。"""
    job = db_client.post(
        "/api/v1/jobs", json={"company": {"name": "测试公司"}, "title": "测试", "raw_jd": "熟悉 Python"}
    ).json()["data"]
    url = f"/api/v1/job-snapshots/{job['latest_snapshot']['id']}/parses"

    response = db_client.post(url, json={"engine": "AI", "confirm_external": True})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    message = response.json()["error"]["message"]
    assert "AI 模型配置" in message
    # 旧实现提示"配置 AI 网关/环境变量"；迁移后必须指向页面内的模型配置。
    assert "环境变量" not in message


def test_optimizer_rejects_invented_indices(db_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """无确认不得发送；模型引用未知条目不得生成候选。"""
    _configure_default_model(db_client)
    calls: list[dict[str, Any]] = []

    async def fake(
        config: gateway.ResolvedAiModel, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """记录实际发送的数据并返回越界索引。"""
        calls.append(input_data)
        return {"experiences": [], "projects": [], "skills": [99], "educations": [], "languages": []}

    monkeypatch.setattr(gateway, "generate", fake)
    db_client.post("/api/v1/profile", json={"full_name": "测试"})
    revision = db_client.post("/api/v1/profile/revisions", json={"reason": "测试"}).json()["data"]
    resume = db_client.post("/api/v1/resumes", json={"name": "测试简历"}).json()["data"]
    version = db_client.post(
        f"/api/v1/resumes/{resume['id']}/versions",
        json={
            "profile_revision_id": revision["id"],
            "document": {"basics": {"full_name": "测试"}, "contact": {"email": "private@example.com"}},
            "created_reason": "测试",
        },
    ).json()["data"]
    url = f"/api/v1/resumes/{resume['id']}/optimize"
    payload = {"base_resume_version_id": version["id"], "target": "后端", "confirm_external": False}
    assert db_client.post(url, json=payload).status_code == 422
    assert not calls
    payload["confirm_external"] = True
    assert db_client.post(url, json=payload).status_code == 422
    assert "private@example.com" not in str(calls)
    assert db_client.get(f"/api/v1/resumes/{resume['id']}/drafts").json()["data"] == []

    async def valid(
        config: gateway.ResolvedAiModel, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """返回有效选择，不增加或修改条目。"""
        return {"experiences": [], "projects": [], "skills": [], "educations": [], "languages": []}

    monkeypatch.setattr(gateway, "generate", valid)
    result = db_client.post(url, json=payload)
    assert result.status_code == 201, result.text
    assert result.json()["data"]["status"] == "DRAFT"
    assert result.json()["data"]["base_resume_version_id"] == version["id"]
