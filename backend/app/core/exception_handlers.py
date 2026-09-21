"""统一异常处理。

把四类异常收口到同一响应契约：领域异常（`AppError`）、请求校验失败、Starlette HTTP 异常、
以及未捕获异常。路由与服务层只负责抛出语义明确的异常，不负责构造错误响应。

安全边界：对外的 `message` 与 `details` 永不包含堆栈、连接串、上游原始错误或请求体原文；
诊断信息只写入服务端日志。
"""

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .errors import AppError, ErrorCode
from .responses import ErrorDetail, error_response

logger = logging.getLogger(__name__)

# Starlette 内置异常到错误码的映射；未列出的状态码统一落到 INTERNAL_ERROR 之外的安全兜底。
_STATUS_CODE_TO_ERROR_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.AUTHENTICATION_REQUIRED,
    403: ErrorCode.PERMISSION_DENIED,
    404: ErrorCode.ROUTE_NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
}

# 未收录状态码的兜底文案，避免把 Starlette 的英文默认提示直接暴露给用户。
_FALLBACK_MESSAGES: dict[int, str] = {
    400: "请求无法处理，请检查后重试。",
    401: "需要登录后才能继续。",
    403: "没有执行该操作的权限。",
    404: "请求的接口不存在。",
    405: "该接口不支持当前请求方法。",
    409: "当前状态与该操作冲突。",
    422: "提交的数据未通过校验。",
    429: "请求过于频繁，请稍后重试。",
}


def _request_id_from_scope(request: Any) -> str | None:
    """从请求作用域读取中间件写入的请求标识。

    参数:
        request: Starlette/FastAPI 请求对象。

    返回:
        str | None: 请求标识；未经过请求上下文中间件时为 None。
    """
    state = getattr(request, "state", None)
    value = getattr(state, "request_id", None)
    return value if isinstance(value, str) else None


async def app_error_handler(request: Any, exc: AppError) -> Any:
    """处理领域异常。

    参数:
        request: 当前请求。
        exc: 领域异常实例。

    返回:
        JSONResponse: 按契约构造的失败响应。

    注意:
        5xx 视为服务端缺陷，记录完整堆栈；4xx 属于可预期的业务失败，只记录告警级结论，
        避免正常业务流转刷满错误日志。
    """
    if exc.status_code >= 500:
        logger.exception(
            "领域异常（服务端错误）",
            extra={"event": "app_error", "error_code": str(exc.code)},
        )
    else:
        logger.warning(
            "领域异常",
            extra={"event": "app_error", "error_code": str(exc.code), "http_status": exc.status_code},
        )
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        request_id=_request_id_from_scope(request),
    )


async def validation_error_handler(request: Any, exc: RequestValidationError) -> Any:
    """处理请求校验失败。

    参数:
        request: 当前请求。
        exc: FastAPI 抛出的校验异常。

    返回:
        JSONResponse: 422 失败响应，`details` 含字段路径与原因。

    注意:
        只保留字段路径与原因，丢弃 pydantic 错误中的 `input`/`ctx` 等内容——它们可能包含
        用户原文或内部对象，属于不应回显的数据。
    """
    details = [
        ErrorDetail(
            field=".".join(str(part) for part in error.get("loc", ())) or None,
            reason=str(error.get("msg", "字段校验失败。")),
        )
        for error in exc.errors()
    ]
    logger.warning(
        "请求校验失败",
        extra={"event": "validation_error", "detail_count": len(details)},
    )
    return error_response(
        status_code=422,
        code=ErrorCode.VALIDATION_ERROR,
        message=_FALLBACK_MESSAGES[422],
        details=details,
        request_id=_request_id_from_scope(request),
    )


async def http_exception_handler(request: Any, exc: StarletteHTTPException) -> Any:
    """处理 Starlette/FastAPI 内置 HTTP 异常。

    参数:
        request: 当前请求。
        exc: 内置 HTTP 异常，常见来源是路由未匹配（404）与方法不支持（405）。

    返回:
        JSONResponse: 与错误码表一致的失败响应。
    """
    code = _STATUS_CODE_TO_ERROR_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail else None
    message = _FALLBACK_MESSAGES.get(exc.status_code) or detail or "请求处理失败。"
    return error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        request_id=_request_id_from_scope(request),
    )


async def unhandled_exception_handler(request: Any, exc: Exception) -> Any:
    """处理未捕获异常。

    参数:
        request: 当前请求。
        exc: 未被其他处理器覆盖的异常。

    返回:
        JSONResponse: 500 失败响应，仅含通用提示与请求标识。

    注意:
        处理器由 Starlette 的 `ServerErrorMiddleware` 调用，位于请求上下文中间件之外，
        因此请求标识通过 `scope.state` 传递；堆栈只进日志，绝不进入响应体。
    """
    logger.exception(
        "未捕获异常",
        extra={"event": "unhandled_exception", "exception_type": type(exc).__name__},
    )
    return error_response(
        status_code=500,
        code=ErrorCode.INTERNAL_ERROR,
        message="服务器内部错误，请稍后重试。",
        request_id=_request_id_from_scope(request),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """在应用上注册统一异常处理器。

    参数:
        app: FastAPI 应用实例。

    注意:
        注册 `Exception` 的处理器等价于自定义 500 处理器：Starlette 会用它替换默认的
        `ServerErrorMiddleware` 行为，从而保证未捕获异常也返回统一契约而非纯文本 500。
    """
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
