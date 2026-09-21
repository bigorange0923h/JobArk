"""请求上下文中间件。

职责是在每个 HTTP 请求上建立 `request_id`、回写 `X-Request-ID` 响应头，并输出一条结构化访问日志。
采用纯 ASGI 实现而非 `BaseHTTPMiddleware`：后者通过额外任务包装响应流，会丢失 ContextVar 的
传播并干扰 SSE 等流式响应，而本中间件依赖 ContextVar 关联日志。

挂载顺序说明：`app.add_middleware` 注册的中间件位于 Starlette `ServerErrorMiddleware` 之内、
`ExceptionMiddleware` 之外。因此已注册异常处理器（含 `AppError`）产生的响应会经过本中间件，
而未捕获异常由外层处理器生成、不经过本中间件——这类响应由异常处理器自行回写请求标识。
"""

import logging
import re
from time import perf_counter

from starlette.datastructures import MutableHeaders

# ASGI 类型在运行期导入：函数签名中的标注会被求值，且 starlette 已是本项目的硬依赖，
# 放在 TYPE_CHECKING 分支只会迫使所有标注写成字符串字面量。
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .context import new_request_id, reset_request_id, set_request_id

logger = logging.getLogger(__name__)

# 入站标识白名单：拒绝过长或含控制字符的值，避免污染日志与响应头（响应头注入）。
_INBOUND_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_STATE_KEY = "request_id"


def resolve_request_id(scope: Scope) -> str:
    """确定本次请求使用的标识。

    参数:
        scope: ASGI 请求作用域。

    返回:
        str: 入站 `X-Request-ID` 合法时沿用（便于与上游网关、前端日志串联），否则生成新标识。
    """
    for name, value in scope.get("headers", []):
        if name.lower() == REQUEST_ID_HEADER.lower().encode():
            candidate = value.decode("latin-1").strip()
            if _INBOUND_REQUEST_ID_PATTERN.fullmatch(candidate):
                return candidate
    return new_request_id()


class RequestContextMiddleware:
    """为每个 HTTP 请求建立可追踪的上下文与访问日志。"""

    def __init__(self, app: ASGIApp) -> None:
        """初始化中间件。

        参数:
            app: 下游 ASGI 应用。
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """处理一次 ASGI 调用。

        参数:
            scope: ASGI 作用域；仅 `http` 类型会被注入上下文。
            receive: ASGI 接收通道。
            send: ASGI 发送通道。

        注意:
            非 HTTP 作用域（lifespan、websocket）直接透传，避免探针与测试客户端受影响。
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(scope)
        token = set_request_id(request_id)
        # 同时写入 scope state：外层异常处理器无法读取已被重置的 ContextVar，
        # 只能通过 scope 传递的 state 获取同一个标识。
        scope.setdefault("state", {})[_REQUEST_ID_STATE_KEY] = request_id

        started_at = perf_counter()
        status_code: int | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # 未捕获异常由外层 ServerErrorMiddleware 处理，这里只负责留下带 request_id 的日志。
            logger.exception(
                "请求处理失败",
                extra={
                    "event": "http_request_failed",
                    "http_method": scope.get("method"),
                    "http_path": scope.get("path"),
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise
        finally:
            if status_code is not None:
                logger.info(
                    "请求完成",
                    extra={
                        "event": "http_request",
                        "http_method": scope.get("method"),
                        "http_path": scope.get("path"),
                        "http_status": status_code,
                        "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                    },
                )
            reset_request_id(token)
