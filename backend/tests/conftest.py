"""测试夹具。

每个测试通过 `create_app` 构建独立应用实例，并挂载仅用于验证契约的探针路由。
探针路由不进入生产入口，避免为测试而在正式应用上暴露调试接口。

测试配置显式禁用 `.env` 加载，防止开发者本地配置让测试结果不可复现。
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings
from app.core.errors import ResourceNotFoundError
from app.core.responses import ApiResponse, success
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """返回测试专用配置。

    返回:
        Settings: 固定测试环境与告警级日志，且不读取 `.env`。
    """
    return Settings(app_env=AppEnv.TEST, log_level="WARNING", _env_file=None)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """构建带契约探针路由的应用实例。

    参数:
        settings: 测试配置。

    返回:
        FastAPI: 可验证校验失败、领域异常与未捕获异常处理的应用。
    """
    application = create_app(settings)

    @application.get("/_probe/echo", response_model=ApiResponse[dict[str, str]])
    async def probe_echo(limit: int) -> ApiResponse[dict[str, str]]:
        """校验探针：`limit` 缺失或非整数时触发 422。"""
        return success({"limit": str(limit)})

    @application.get("/_probe/missing", response_model=ApiResponse[dict[str, str]])
    async def probe_missing() -> ApiResponse[dict[str, str]]:
        """领域异常探针：模拟资源不存在。"""
        raise ResourceNotFoundError("测试用的资源不存在。")

    @application.get("/_probe/crash", response_model=ApiResponse[dict[str, str]])
    async def probe_crash() -> ApiResponse[dict[str, str]]:
        """未捕获异常探针：异常原文不得出现在响应中。"""
        raise RuntimeError("内部实现细节：不应出现在响应体中")

    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """返回测试客户端。

    参数:
        app: 待测应用。

    返回:
        Iterator[TestClient]: 关闭异常透传的客户端，以便验证 500 响应契约。
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
