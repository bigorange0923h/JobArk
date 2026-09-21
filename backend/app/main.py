"""JobArk 后端唯一应用入口。

本模块是后端唯一的 FastAPI 入口：`create_app` 负责组装应用实例与系统级路由，
模块级 `app` 供 ASGI 服务器直接引用（如 `uvicorn app.main:app`）。
领域模块的路由挂载点集中在这一处，避免入口分散到各模块导致启动行为不可追踪。
"""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """健康检查响应体。"""

    status: Literal["ok"] = Field(description="服务存活状态；进程可响应请求时固定为 ok。")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    返回:
        FastAPI: 已注册系统级路由的应用实例。业务领域路由在阶段 0 之后按模块逐个挂载。

    注意:
        `/health` 当前直接返回业务载荷。AGENTS.md 要求的统一响应包装
        （`success`/`data`/`meta`）属于阶段 0 第 3 项，届时该接口结构会一并调整。
    """
    application = FastAPI(
        title="JobArk API",
        description="JobArk 个人求职工作台后端接口。",
        openapi_tags=[{"name": "system", "description": "健康检查等系统级接口。"}],
    )

    @application.get(
        "/health",
        tags=["system"],
        summary="健康检查",
        description="探测后端进程是否可响应请求，供本地启动自检与后续容器编排探针使用。",
        response_model=HealthResponse,
    )
    async def health() -> HealthResponse:
        """返回进程存活状态。

        返回:
            HealthResponse: 固定为 `ok` 的存活状态。

        注意:
            本接口不校验数据库或外部依赖可用性，因此不能作为就绪探针使用。
        """
        return HealthResponse(status="ok")

    return application


app = create_app()
