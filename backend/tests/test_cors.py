"""跨域（CORS）能力：默认关闭、显式白名单启用、空白名单的解析方式。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings
from app.main import create_app

_ALLOWED_ORIGIN = "http://localhost:5173"


def _settings(cors_allowed_origins: list[str]) -> Settings:
    """构造带指定跨域白名单的测试配置。

    参数:
        cors_allowed_origins: 允许的来源列表。

    返回:
        Settings: 不读取 `.env` 的测试配置。
    """
    return Settings(
        app_env=AppEnv.TEST,
        log_level="WARNING",
        cors_allowed_origins=cors_allowed_origins,
        # 与 conftest 一致：运行期禁用 .env 读取，该参数未在生成签名中声明。
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


def test_preflight_is_rejected_when_no_origin_is_configured(client: TestClient) -> None:
    """默认（白名单为空）不应挂载 CORS，跨域预检得不到放行头。"""
    response = client.options(
        "/health",
        headers={"Origin": _ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_simple_request_gets_no_cors_header_by_default(client: TestClient) -> None:
    """默认关闭时，即便请求带了 Origin，也不应回写放行头。"""
    response = client.get("/health", headers={"Origin": _ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_preflight_allows_whitelisted_origin() -> None:
    """白名单内的来源应通过预检。"""
    application: FastAPI = create_app(_settings([_ALLOWED_ORIGIN]))

    with TestClient(application) as client:
        response = client.options(
            "/health",
            headers={"Origin": _ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert "GET" in response.headers["access-control-allow-methods"]


def test_actual_request_exposes_request_id_header() -> None:
    """实际请求应放行来源并暴露请求标识响应头。

    注意:
        `expose_headers` 只作用于实际请求，预检响应不会带该头，因此这条断言必须落在 GET 上。
        不暴露该头时，跨域场景下前端脚本读不到 `X-Request-ID`，排查会丢失请求标识。
    """
    application: FastAPI = create_app(_settings([_ALLOWED_ORIGIN]))

    with TestClient(application) as client:
        response = client.get("/health", headers={"Origin": _ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]


def test_preflight_rejects_origin_outside_whitelist() -> None:
    """白名单之外的来源不得被放行。"""
    application: FastAPI = create_app(_settings([_ALLOWED_ORIGIN]))

    with TestClient(application) as client:
        response = client.options(
            "/health",
            headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
        )

    assert response.headers.get("access-control-allow-origin") != "http://evil.example"


def test_origins_are_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量使用逗号分隔写法，且空项必须被丢弃。

    这条断言同时守住一个容易踩的坑：pydantic-settings 默认会尝试把复杂字段按 JSON 解析，
    若不关闭该行为，`a,b` 这种写法会直接抛配置错误。
    """
    monkeypatch.setenv("JOBARK_CORS_ALLOWED_ORIGINS", "http://a.example, http://b.example ,")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.cors_allowed_origins == ["http://a.example", "http://b.example"]
