"""请求标识的建立、透传与防护。"""

import re

from fastapi.testclient import TestClient

_GENERATED_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def test_inbound_request_id_is_reused(client: TestClient) -> None:
    """合法的入站标识应被沿用，便于与上游网关或前端日志串联。"""
    response = client.get("/health", headers={"X-Request-ID": "gateway-abc.123"})

    assert response.status_code == 200
    assert response.json()["meta"]["request_id"] == "gateway-abc.123"
    assert response.headers["X-Request-ID"] == "gateway-abc.123"


def test_invalid_inbound_request_id_is_replaced(client: TestClient) -> None:
    """非法入站标识必须被丢弃，避免日志注入与响应头注入。"""
    response = client.get("/health", headers={"X-Request-ID": "bad id\r\ninjected"})

    assert response.status_code == 200
    request_id = response.json()["meta"]["request_id"]
    assert request_id != "bad id\r\ninjected"
    assert _GENERATED_ID_PATTERN.fullmatch(request_id)


def test_request_id_is_unique_per_request(client: TestClient) -> None:
    """未提供标识的两次请求应得到不同标识。"""
    first = client.get("/health").json()["meta"]["request_id"]
    second = client.get("/health").json()["meta"]["request_id"]

    assert first != second
