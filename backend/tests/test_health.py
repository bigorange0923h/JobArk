"""健康检查与成功响应契约。"""

from fastapi.testclient import TestClient


def test_health_returns_success_envelope(client: TestClient) -> None:
    """健康检查应返回统一成功包装，且响应头与 meta 的请求标识一致。"""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == {"status": "ok"}
    assert body["meta"]["request_id"]
    assert response.headers["X-Request-ID"] == body["meta"]["request_id"]


def test_health_declares_envelope_in_openapi(client: TestClient) -> None:
    """OpenAPI 必须描述统一包装结构，避免契约只存在于实现里。"""
    schema = client.get("/openapi.json").json()
    health_response = schema["paths"]["/health"]["get"]["responses"]["200"]

    assert health_response["content"]["application/json"]["schema"]["$ref"].endswith("ApiResponse_HealthResponse_")
