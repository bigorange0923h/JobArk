"""结构化日志。

统一输出单行 JSON，固定字段为 `timestamp`、`level`、`logger`、`service`、`request_id`、`message`，
调用方通过 `extra=` 追加的字段会被合并进同一行，便于按字段检索而无需正则解析。
uvicorn 自带的访问日志会产生与本应用访问日志无关联的重复行，因此在此关闭，访问日志由
`core.middleware` 统一产出，从而保证每行都带 `request_id`。
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from .context import get_request_id

# LogRecord 的标准属性集合：用于区分调用方通过 extra= 传入的自定义字段。
_STANDARD_ATTRS = frozenset(
    logging.LogRecord(name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None).__dict__
)


class JsonLogFormatter(logging.Formatter):
    """把日志记录序列化为单行 JSON。"""

    def __init__(self, service: str) -> None:
        """初始化格式化器。

        参数:
            service: 写入每行日志的服务名，便于多服务聚合时区分来源。
        """
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        """格式化单条日志记录。

        参数:
            record: 标准库日志记录。

        返回:
            str: 单行 JSON；异常信息序列化到 `exception` 字段而不直接打印到 stdout。

        注意:
            使用 `default=str` 兜底非 JSON 原生类型，保证格式化阶段不会因日志内容抛出异常——
            日志失败不应影响请求处理。
        """
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": self._service,
            "request_id": get_request_id(),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(service: str, level: str) -> None:
    """配置根 logger，使全进程日志统一走 JSON 格式化。

    参数:
        service: 写入日志的 `service` 字段值。
        level: 根 logger 级别，取值为标准级别名。

    注意:
        本函数是幂等的，会先清空根 logger 的既有 handler，避免 uvicorn 与测试重复初始化时
        出现重复输出。
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter(service))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn 会给自身 logger 装 handler 且不向上传播，导致其日志绕过 JSON 格式。
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    # 访问日志由中间件统一产出（含 request_id），这里关闭 uvicorn 的重复实现。
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.disabled = True
