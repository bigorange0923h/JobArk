"""领域异常与稳定错误码。

错误码是前端与外部调用方依赖的稳定契约，一经发布不得随意改名；新增错误码必须同步更新
ADR 与相关文档。所有面向用户的失败都必须抛出 `AppError` 子类，由统一异常处理器转换为
`ApiErrorResponse`，禁止在路由中散落 `try/except` 或返回裸字符串。
"""

from enum import StrEnum
from typing import ClassVar

from .responses import ErrorDetail


class ErrorCode(StrEnum):
    """对外暴露的错误码。

    每个取值对应一个语义明确的失败类别，与 HTTP 状态码的对应关系见 ADR 0001。
    """

    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """应用异常基类。

    子类通过类变量声明错误码与状态码，实例只承载本次失败的信息与细节。

    注意:
        基类默认映射为 500，仅用于兜底；业务与领域代码应抛出语义明确的子类，
        因为错误码会被前端和调用方按契约处理。
    """

    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL_ERROR
    status_code: ClassVar[int] = 500
    default_message: ClassVar[str] = "服务器内部错误，请稍后重试。"

    def __init__(self, message: str | None = None, details: list[ErrorDetail] | None = None) -> None:
        """初始化异常。

        参数:
            message: 面向用户的安全提示；为 None 时使用类默认文案。禁止传入堆栈、连接串等内部信息。
            details: 结构化的失败细节，例如字段级原因。
        """
        self.message = message or self.default_message
        self.details = details or []
        super().__init__(self.message)


class BadRequestError(AppError):
    """请求语义非法（400）。"""

    code = ErrorCode.BAD_REQUEST
    status_code = 400
    default_message = "请求无法处理，请检查后重试。"


class ValidationFailedError(AppError):
    """请求数据未通过校验（422）。"""

    code = ErrorCode.VALIDATION_ERROR
    status_code = 422
    default_message = "提交的数据未通过校验。"


class AuthenticationRequiredError(AppError):
    """未提供有效身份（401）。"""

    code = ErrorCode.AUTHENTICATION_REQUIRED
    status_code = 401
    default_message = "需要登录后才能继续。"


class PermissionDeniedError(AppError):
    """身份有效但无权限（403）。"""

    code = ErrorCode.PERMISSION_DENIED
    status_code = 403
    default_message = "没有执行该操作的权限。"


class ResourceNotFoundError(AppError):
    """领域资源不存在（404）。"""

    code = ErrorCode.RESOURCE_NOT_FOUND
    status_code = 404
    default_message = "请求的资源不存在。"


class ConflictError(AppError):
    """与现有状态冲突（409），例如重复申请或版本冲突。"""

    code = ErrorCode.CONFLICT
    status_code = 409
    default_message = "当前状态与该操作冲突。"


class RateLimitedError(AppError):
    """触发限流（429）。"""

    code = ErrorCode.RATE_LIMITED
    status_code = 429
    default_message = "请求过于频繁，请稍后重试。"
