"""JobArk 后端唯一应用入口。

本模块是后端唯一的 FastAPI 入口：`create_app` 负责组装应用实例与系统级路由，
模块级 `app` 供 ASGI 服务器直接引用（如 `uvicorn app.main:app`）。
领域模块的路由挂载点集中在这一处，避免入口分散到各模块导致启动行为不可追踪。
"""

from typing import Literal

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

from .core.config import Settings, get_settings
from .core.exception_handlers import register_exception_handlers
from .core.logging import setup_logging
from .core.middleware import RequestContextMiddleware
from .core.responses import ApiResponse, success


class HealthResponse(BaseModel):
    """健康检查载荷。"""

    status: Literal["ok"] = Field(description="服务存活状态；进程可响应请求时固定为 ok。")


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    参数:
        settings: 运行配置；缺省时读取进程级配置单例，测试可注入自定义配置。

    返回:
        FastAPI: 已装配日志、请求上下文中间件、统一异常处理与系统级路由的应用实例。

    注意:
        不开启 `debug`：FastAPI 的调试模式会把异常堆栈直接渲染进响应体，
        与"响应不得暴露堆栈、密钥或上游原始错误"的约束冲突。
    """
    resolved_settings = settings or get_settings()
    setup_logging(resolved_settings.app_name, resolved_settings.log_level)

    application = FastAPI(
        title=f"{resolved_settings.app_name} API",
        description="JobArk 个人求职工作台后端接口。",
        openapi_tags=[
            {"name": "system", "description": "健康检查等系统级接口，路径不随业务版本变化。"},
        ],
    )

    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)

    @application.get(
        "/health",
        tags=["system"],
        summary="健康检查",
        description="探测后端进程是否可响应请求，并返回统一响应契约与请求标识。",
        response_model=ApiResponse[HealthResponse],
    )
    async def health() -> ApiResponse[HealthResponse]:
        """返回进程存活状态。

        返回:
            ApiResponse[HealthResponse]: 包装后的存活状态。

        注意:
            本接口不校验数据库或外部依赖可用性，因此不能作为就绪探针使用。
        """
        return success(HealthResponse(status="ok"))

    # 业务领域路由的统一挂载点：阶段 1 起各领域模块的 router 在此逐个 include，
    # 统一挂到 /api/v1，使后续版本演进不需要改动已发布的路径。
    api_v1 = APIRouter(prefix=resolved_settings.api_v1_prefix)
    application.include_router(api_v1)

    return application


app = create_app()
