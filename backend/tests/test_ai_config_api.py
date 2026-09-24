"""AI 模型配置接口的集成测试：只使用专用测试库，外部 HTTP 一律替换。

覆盖需求中的核心边界：

- 凭据边界：读取 DTO 不含明文或密文，数据库只保存可逆密文。
- 默认模型唯一性：首个模型自动默认，切换默认原子地清除旧标记。
- 一致性：默认模型不能被直接停用或删除；停用服务商不得继续保有默认模型。
- 失败反馈：不安全地址为 422，重复标识与删除默认模型为 409，连接失败不修改数据。

这些测试直接请求真实迁移产物，因此不使用 `create_all` 或手工建表。
"""

import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.llm import gateway
from app.core.errors import ValidationFailedError

API = "/api/v1/ai"


def _create_provider(client: TestClient, **overrides: Any) -> dict[str, Any]:
    """创建服务商并返回响应数据。

    参数:
        client: 指向测试库的客户端。
        **overrides: 覆盖默认请求字段。

    返回:
        dict[str, Any]: 服务商读取 DTO。
    """
    payload: dict[str, Any] = {
        "name": "本地兼容服务",
        "base_url": "http://localhost:11434/v1",
        "api_key": "secret-value",
    }
    payload.update(overrides)
    response = client.post(f"{API}/providers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _create_model(client: TestClient, provider_id: str, **overrides: Any) -> dict[str, Any]:
    """在指定服务商下创建模型并返回响应数据。

    参数:
        client: 指向测试库的客户端。
        provider_id: 所属服务商主键。
        **overrides: 覆盖默认请求字段。

    返回:
        dict[str, Any]: 模型读取 DTO。
    """
    payload: dict[str, Any] = {"name": "本地模型", "remote_model_id": "qwen3"}
    payload.update(overrides)
    response = client.post(f"{API}/providers/{provider_id}/models", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _all_models(client: TestClient) -> list[dict[str, Any]]:
    """扁平化读取全部服务商下的模型，便于断言默认标记。"""
    providers = client.get(f"{API}/providers").json()["data"]
    return [model for provider in providers for model in provider["models"]]


def test_first_model_is_default_and_key_is_never_returned(db_client: TestClient) -> None:
    """首个模型自动成为唯一默认模型，读取结果不含明文或密文。"""
    provider = _create_provider(db_client)
    assert "api_key" not in provider
    assert "ciphertext" not in provider
    assert provider["api_key_configured"] is True
    assert provider["api_key_mask"] == "••••alue"

    model = _create_model(db_client, provider["id"])
    assert model["is_default"] is True

    listed = db_client.get(f"{API}/providers").json()["data"]
    assert listed[0]["has_default_model"] is True
    assert listed[0]["models"][0]["id"] == model["id"]


def test_read_responses_never_contain_key_material(db_client: TestClient) -> None:
    """读取响应既不含明文 Key，也不含密文字段。"""
    _create_provider(db_client, api_key="secret-value")
    raw = db_client.get(f"{API}/providers").text
    assert "secret-value" not in raw
    assert "ciphertext" not in raw


def test_provider_key_is_encrypted_at_rest(db_client: TestClient, test_database_url: str) -> None:
    """数据库列保存的是可逆密文，绝不等同于明文。"""
    provider = _create_provider(db_client, api_key="secret-value")

    async def read_ciphertext() -> str | None:
        """直接读取配置表，验证落库内容不是明文。"""
        engine = create_async_engine(test_database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                return await connection.scalar(
                    text("SELECT api_key_ciphertext FROM ai_providers WHERE id = :id"),
                    {"id": uuid.UUID(provider["id"])},
                )
        finally:
            await engine.dispose()

    ciphertext = asyncio.run(read_ciphertext())
    assert ciphertext is not None
    assert "secret-value" not in ciphertext


def test_second_model_is_not_default_and_switching_is_atomic(db_client: TestClient) -> None:
    """同一时刻只有一个默认模型，切换默认会清除旧标记。"""
    provider = _create_provider(db_client)
    first = _create_model(db_client, provider["id"], remote_model_id="qwen3")
    second = _create_model(db_client, provider["id"], name="工作模型", remote_model_id="gpt-4.1-mini")
    assert first["is_default"] is True
    assert second["is_default"] is False

    switched = db_client.post(f"{API}/models/{second['id']}/default")
    assert switched.status_code == 200, switched.text
    assert switched.json()["data"]["is_default"] is True

    models = _all_models(db_client)
    assert sum(1 for model in models if model["is_default"]) == 1
    assert next(model for model in models if model["id"] == first["id"])["is_default"] is False


def test_default_model_cannot_be_disabled_or_deleted(db_client: TestClient) -> None:
    """默认模型必须先改默认，才能停用或删除。"""
    provider = _create_provider(db_client)
    model = _create_model(db_client, provider["id"])

    disabled = db_client.patch(f"{API}/models/{model['id']}", json={"version": model["version"], "is_enabled": False})
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "CONFLICT"

    deleted = db_client.request("DELETE", f"{API}/models/{model['id']}", json={"confirmed": True})
    assert deleted.status_code == 409
    assert any(item["id"] == model["id"] for item in _all_models(db_client))


def test_delete_requires_explicit_confirmation(db_client: TestClient) -> None:
    """删除必须确认；确认后非默认模型被移除，未确认不产生副作用。"""
    provider = _create_provider(db_client)
    _create_model(db_client, provider["id"], remote_model_id="qwen3")
    extra = _create_model(db_client, provider["id"], name="备用模型", remote_model_id="qwen2.5")

    denied = db_client.request("DELETE", f"{API}/models/{extra['id']}", json={"confirmed": False})
    assert denied.status_code == 422
    assert any(item["id"] == extra["id"] for item in _all_models(db_client))

    removed = db_client.request("DELETE", f"{API}/models/{extra['id']}", json={"confirmed": True})
    assert removed.status_code == 200, removed.text
    assert all(item["id"] != extra["id"] for item in _all_models(db_client))


def test_disabled_provider_cannot_hold_default_model(db_client: TestClient) -> None:
    """停用或删除服务商前必须先解除其默认模型。"""
    provider = _create_provider(db_client)
    model = _create_model(db_client, provider["id"])

    disabled = db_client.patch(
        f"{API}/providers/{provider['id']}", json={"version": provider["version"], "is_enabled": False}
    )
    assert disabled.status_code == 409
    deleted = db_client.request("DELETE", f"{API}/providers/{provider['id']}", json={"confirmed": True})
    assert deleted.status_code == 409
    assert any(item["id"] == model["id"] for item in _all_models(db_client))

    # 切换到另一个启用模型后，原默认服务商才可停用。
    other_provider = _create_provider(db_client, name="云端兼容服务", base_url="https://example.test/v1")
    other_model = _create_model(db_client, other_provider["id"], name="云端模型", remote_model_id="gpt-4.1")
    assert db_client.post(f"{API}/models/{other_model['id']}/default").status_code == 200
    assert (
        db_client.patch(
            f"{API}/providers/{provider['id']}", json={"version": provider["version"], "is_enabled": False}
        ).status_code
        == 200
    )


def test_duplicate_provider_name_and_remote_model_id_conflict(db_client: TestClient) -> None:
    """服务商名称与同服务商下的远端模型标识都不可重复。"""
    provider = _create_provider(db_client)
    duplicate_name = db_client.post(
        f"{API}/providers", json={"name": provider["name"], "base_url": "https://example.test/v1"}
    )
    assert duplicate_name.status_code == 409

    _create_model(db_client, provider["id"], remote_model_id="qwen3")
    duplicate_model = db_client.post(
        f"{API}/providers/{provider['id']}/models", json={"name": "重复模型", "remote_model_id": "qwen3"}
    )
    assert duplicate_model.status_code == 409


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.com/v1",
        "https://user:pass@example.com/v1",
        "https://example.com/v1?tenant=1",
        "https://example.com/v1#section",
        "ftp://example.com/v1",
    ],
)
def test_unsafe_provider_urls_are_rejected(db_client: TestClient, base_url: str) -> None:
    """非 HTTPS、带凭据、带查询参数或片段的地址一律拒绝。"""
    response = db_client.post(f"{API}/providers", json={"name": "不安全服务", "base_url": base_url})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_provider_key_update_semantics(db_client: TestClient) -> None:
    """未提交或空值保留原密文，只有提交新值才替换。"""
    provider = _create_provider(db_client, api_key="secret-value")

    renamed = db_client.patch(
        f"{API}/providers/{provider['id']}", json={"version": provider["version"], "name": "改名后的服务商"}
    )
    assert renamed.status_code == 200, renamed.text
    renamed_data = renamed.json()["data"]
    assert renamed_data["api_key_configured"] is True
    assert renamed_data["api_key_mask"] == "••••alue"

    blank = db_client.patch(
        f"{API}/providers/{renamed_data['id']}", json={"version": renamed_data["version"], "api_key": ""}
    )
    assert blank.status_code == 200, blank.text
    assert blank.json()["data"]["api_key_configured"] is True
    assert blank.json()["data"]["api_key_mask"] == "••••alue"

    replaced = db_client.patch(
        f"{API}/providers/{renamed_data['id']}",
        json={"version": blank.json()["data"]["version"], "api_key": "new-secret"},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["data"]["api_key_mask"] == "••••cret"


def test_provider_without_key_reports_not_configured(db_client: TestClient) -> None:
    """未提交 Key 的服务商明确显示为未配置，不伪造掩码。"""
    provider = _create_provider(db_client, api_key=None)
    assert provider["api_key_configured"] is False
    assert provider["api_key_mask"] is None


def test_connection_failure_does_not_modify_configuration(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """连接测试失败时返回安全错误与请求标识，且不改变默认状态或版本。"""
    provider = _create_provider(db_client)
    model = _create_model(db_client, provider["id"])

    async def failing(config: gateway.ResolvedAiModel) -> None:
        """模拟上游不可用；异常文案不含凭据或上游原文。"""
        raise ValidationFailedError("AI 请求失败或结果无效，原始资料已保留，请稍后手动重试。")

    monkeypatch.setattr("app.ai.service.gateway.check_connection", failing)

    response = db_client.post(f"{API}/models/{model['id']}/test")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["meta"]["request_id"]
    assert "secret-value" not in response.text

    after = _all_models(db_client)
    assert after[0]["id"] == model["id"]
    assert after[0]["is_default"] is True
    assert after[0]["version"] == model["version"]


def test_connection_success_uses_decrypted_provider_credentials(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """连接测试使用解密后的服务商凭据，且响应不回显凭据。"""
    provider = _create_provider(db_client, api_key="secret-value")
    model = _create_model(db_client, provider["id"])
    captured: dict[str, gateway.ResolvedAiModel] = {}

    async def succeeding(config: gateway.ResolvedAiModel) -> None:
        """记录解析出的请求配置，不实际联网。"""
        captured["config"] = config

    monkeypatch.setattr("app.ai.service.gateway.check_connection", succeeding)

    response = db_client.post(f"{API}/models/{model['id']}/test")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["ok"] is True
    assert captured["config"].api_key == "secret-value"
    assert captured["config"].remote_model_id == "qwen3"
    assert captured["config"].base_url == "http://localhost:11434/v1"
    assert "secret-value" not in response.text


def test_model_and_provider_not_found(db_client: TestClient) -> None:
    """引用不存在的服务商或模型时返回 404，而不是 500。"""
    provider = _create_provider(db_client)
    missing_provider = db_client.post(
        f"{API}/providers/{uuid.uuid4()}/models", json={"name": "模型", "remote_model_id": "qwen3"}
    )
    assert missing_provider.status_code == 404

    missing_model = db_client.post(f"{API}/models/{uuid.uuid4()}/default")
    assert missing_model.status_code == 404

    stale_version = db_client.patch(f"{API}/providers/{provider['id']}", json={"version": 999, "name": "过期更新"})
    assert stale_version.status_code == 409
