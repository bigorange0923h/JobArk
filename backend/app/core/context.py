"""请求级上下文的载体。

`request_id` 通过 ContextVar 传递，使中间件、日志与响应构造在不显式传参的情况下共享同一个标识。
ContextVar 在 asyncio 任务间是复制语义，因此并发请求不会互相串号；请求结束时必须重置，
否则同一任务后续复用时可能读到过期标识。
"""

from contextvars import ContextVar, Token
from uuid import uuid4

_REQUEST_ID: ContextVar[str | None] = ContextVar("jobark_request_id", default=None)


def new_request_id() -> str:
    """生成新的请求标识。

    返回:
        str: 32 位十六进制字符串，便于日志检索且不含需要转义的字符。
    """
    return uuid4().hex


def set_request_id(request_id: str) -> Token[str | None]:
    """在当前上下文中写入请求标识。

    参数:
        request_id: 本次请求的标识。

    返回:
        Token[str | None]: 供 `reset_request_id` 还原上下文，避免请求间污染。
    """
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """还原请求标识上下文。

    参数:
        token: `set_request_id` 返回的令牌。
    """
    _REQUEST_ID.reset(token)


def get_request_id() -> str | None:
    """读取当前上下文的请求标识。

    返回:
        str | None: 请求进行中时为标识字符串，请求上下文之外为 None。
    """
    return _REQUEST_ID.get()


def ensure_request_id() -> str:
    """读取请求标识，缺失时兜底生成。

    用于响应构造：契约要求 `meta.request_id` 永不为空；但在请求上下文之外（例如直接调用
    领域服务的测试或后台任务）没有中间件写入标识，此时生成一个新标识而不是返回空值。

    返回:
        str: 可写入响应的请求标识。
    """
    return get_request_id() or new_request_id()
