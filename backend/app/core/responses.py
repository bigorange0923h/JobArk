"""统一响应契约。

成功响应固定为 `{success, data, meta}`，失败响应固定为 `{success, error, meta}`，分页等附加信息
放入 `meta`。契约采用显式包装而非中间件改写响应体：中途改写无法可靠区分 SSE、文件下载与
二进制响应，且会让类型检查失去对路由返回值的约束。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Generic, Literal, TypeVar

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .context import ensure_request_id

if TYPE_CHECKING:
    from .errors import ErrorCode

T = TypeVar("T")


class ResponseMeta(BaseModel):
    """响应的追踪信息。"""

    request_id: str = Field(description="本次请求的唯一标识，可用于检索服务端日志。")


class ApiResponse(BaseModel, Generic[T]):
    """成功响应包装。

    路由显式返回本模型，使 OpenAPI 能完整描述 `data` 的结构。
    """

    success: Literal[True] = Field(default=True, description="成功响应固定为 true。")
    data: T = Field(description="业务载荷；列表与分页结果放在此处。")
    meta: ResponseMeta = Field(description="追踪信息。")


class ErrorDetail(BaseModel):
    """单项错误细节。"""

    field: str | None = Field(
        default=None,
        description="出错字段路径（点号分隔）；非字段级错误为 null。",
    )
    reason: str = Field(description="面向用户的失败原因，不得包含内部实现细节。")


class ApiError(BaseModel):
    """错误对象。"""

    code: str = Field(description="稳定错误码，取值见 ADR 0001 的错误码表。")
    message: str = Field(description="面向用户的安全提示。")
    details: list[ErrorDetail] = Field(
        default_factory=list[ErrorDetail],
        description="结构化的失败细节。",
    )


class ApiErrorResponse(BaseModel):
    """失败响应包装。"""

    success: Literal[False] = Field(default=False, description="失败响应固定为 false。")
    error: ApiError = Field(description="错误对象。")
    meta: ResponseMeta = Field(description="追踪信息。")


def success(data: T) -> ApiResponse[T]:
    """构造成功响应。

    参数:
        data: 业务载荷。

    返回:
        ApiResponse[T]: 已填充 `request_id` 的成功响应；请求上下文缺失时兜底生成标识。
    """
    return ApiResponse[T](data=data, meta=ResponseMeta(request_id=ensure_request_id()))


def error_response(
    *,
    status_code: int,
    code: ErrorCode | str,
    message: str,
    details: Sequence[ErrorDetail] = (),
    request_id: str | None = None,
) -> JSONResponse:
    """构造失败响应。

    参数:
        status_code: HTTP 状态码，必须与错误码语义一致，不能用 200 包装失败。
        code: 稳定错误码。
        message: 面向用户的安全提示。
        details: 结构化失败细节。
        request_id: 显式指定的请求标识；缺省时从上下文读取。

    返回:
        JSONResponse: 已写入 `X-Request-ID` 响应头的失败响应。

    注意:
        中间件只覆盖经过它的响应；由外层中间件（未捕获异常）生成的响应不经过中间件的发送钩子，
        因此这里统一回写请求标识，保证任何失败响应都能被日志追踪。
    """
    resolved_request_id = request_id or ensure_request_id()
    payload = ApiErrorResponse(
        error=ApiError(code=str(code), message=message, details=list(details)),
        meta=ResponseMeta(request_id=resolved_request_id),
    )
    response = JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
    response.headers["X-Request-ID"] = resolved_request_id
    return response
