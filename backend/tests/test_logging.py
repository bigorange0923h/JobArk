"""结构化日志格式与请求关联。

日志是可观测性契约的一部分：字段名一旦被采集系统或检索脚本依赖就不能随意更名，
因此这里对字段集合与 JSON 可解析性做显式断言。
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.logging import JsonLogFormatter

_REQUIRED_FIELDS = {"timestamp", "level", "logger", "service", "request_id", "message"}


def test_formatter_emits_single_line_json() -> None:
    """格式化结果必须是单行可解析 JSON，禁止换行破坏逐行采集。"""
    formatter = JsonLogFormatter(service="JobArk")
    record = logging.LogRecord(
        name="app.core.demo",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="演示日志",
        args=(),
        exc_info=None,
    )
    record.http_status = 200

    formatted = formatter.format(record)
    payload = json.loads(formatted)

    assert "\n" not in formatted
    assert _REQUIRED_FIELDS.issubset(payload)
    assert payload["service"] == "JobArk"
    assert payload["message"] == "演示日志"
    assert payload["http_status"] == 200


def test_formatter_serializes_exception_into_field() -> None:
    """异常堆栈应序列化进 `exception` 字段，而不是泄漏到响应或破坏 JSON 结构。"""
    formatter = JsonLogFormatter(service="JobArk")
    try:
        raise RuntimeError("模拟故障")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            name="app.core.demo",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="失败",
            args=(),
            exc_info=sys.exc_info(),
        )

    payload = json.loads(formatter.format(record))

    assert "RuntimeError" in payload["exception"]
    assert "\n" in payload["exception"]


def test_access_log_carries_request_id_and_status(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    """访问日志必须与响应用同一个请求标识，且包含方法、路径与状态码。"""
    with caplog.at_level(logging.INFO, logger="app.core.middleware"):
        response = client.get("/health", headers={"X-Request-ID": "log-correlation-1"})

    access_records = [record for record in caplog.records if getattr(record, "event", None) == "http_request"]

    assert len(access_records) == 1
    record = access_records[0]
    assert record.http_status == response.status_code
    assert record.http_method == "GET"
    assert record.http_path == "/health"
    assert record.duration_ms >= 0
    assert response.json()["meta"]["request_id"] == "log-correlation-1"
