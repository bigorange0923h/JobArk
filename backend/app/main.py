"""JobArk 后端唯一应用入口。

本模块是后端唯一的 FastAPI 入口：`create_app` 负责组装应用实例与系统级路由，
模块级 `app` 供 ASGI 服务器直接引用（如 `uvicorn app.main:app`）。
领域模块的路由挂载点集中在这一处，避免入口分散到各模块导致启动行为不可追踪。
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .core.config import Settings, get_settings
from .core.database import Database
from .core.exception_handlers import register_exception_handlers
from .core.logging import setup_logging
from .core.middleware import RequestContextMiddleware
from .core.responses import ApiResponse, success
from .modules.profile.router import router as profile_router
from .modules.resume.router import router as resume_router


class HealthResponse(BaseModel):
    """健康检查载荷。"""

    status: Literal["ok"] = Field(description="服务存活状态；进程可响应请求时固定为 ok。")


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    参数:
        settings: 运行配置；缺省时读取进程级配置单例，测试可注入自定义配置。

    返回:
        FastAPI: 已装配日志、请求上下文中间件、统一异常处理、数据库持有者与系统级路由的应用实例。

    注意:
        不开启 `debug`：FastAPI 的调试模式会把异常堆栈直接渲染进响应体，
        与"响应不得暴露堆栈、密钥或上游原始错误"的约束冲突。
    """
    resolved_settings = settings or get_settings()
    setup_logging(resolved_settings.app_name, resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        """应用生命周期：启动时创建数据库持有者，退出时释放连接池。

        参数:
            application: 当前应用实例；数据库持有者写入 `app.state.database`。

        返回:
            AsyncGenerator[None]: 生命周期上下文。返回值标注为 `AsyncGenerator`
            而非 `AsyncIterator`：`@asynccontextmanager` 对后者已弃用。

        注意:
            引擎创建是惰性的，不会在启动时建立连接。数据库暂时不可用时服务仍可启动、
            `/health` 仍可用，真实故障在首次查询时以明确错误暴露，而不是让整个服务起不来。
        """
        application.state.database = Database(resolved_settings)
        try:
            yield
        finally:
            await application.state.database.dispose()

    application = FastAPI(
        title=f"{resolved_settings.app_name} API",
        description="JobArk 个人求职工作台后端接口。",
        openapi_tags=[
            {"name": "system", "description": "健康检查等系统级接口，路径不随业务版本变化。"},
        ],
        lifespan=lifespan,
    )

    application.add_middleware(RequestContextMiddleware)
    if resolved_settings.cors_allowed_origins:
        # 后注册的中间件在外层：CORS 包住请求上下文中间件，使预检请求直接由 CORS 应答，
        # 不进入访问日志，也不触碰业务逻辑。
        #
        # 已知限制：Starlette 的 ServerErrorMiddleware 始终在最外层，未捕获异常产生的 500
        # 不经过 CORS，浏览器会把跨域场景下的 500 报成 CORS 错误。开发期使用 Vite 代理同源访问，
        # 不触发该问题；分离部署时排查 500 需直接打后端地址。
        application.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_allowed_origins,
            # 当前没有凭据式认证；开启后浏览器会携带 Cookie 跨域，需与认证方案一起评估。
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-Request-ID"],
            # 不暴露该头时前端脚本读不到它，跨域排查会丢失请求标识。
            expose_headers=["X-Request-ID"],
        )
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

    # 业务领域路由的统一挂载点：各领域模块的 router 在此逐个 include，
    # 统一挂到 /api/v1，使后续版本演进不需要改动已发布的路径。
    api_v1 = APIRouter(prefix=resolved_settings.api_v1_prefix)
    api_v1.include_router(profile_router)
    api_v1.include_router(resume_router)
    application.include_router(api_v1)

    return application


app = create_app()
