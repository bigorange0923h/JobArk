"""默认模型网关的协议、地址与失败边界；测试不访问网络。

网关是唯一的外部 HTTP 边界，因此这些测试关注三件事：

- 请求形状：OpenAI 兼容的 `/chat/completions`、模型标识、结构化输出与鉴权头。
- 地址边界：只允许 HTTPS 或本地回环 HTTP，且拒绝凭据、查询参数与片段。
- 失败边界：超时、非 2xx、重定向、非 JSON、响应超限与缺少内容都映射为安全错误，
  不泄漏上游原文或凭据，也不自动重试。
"""

import asyncio
import json
import urllib.error
from typing import Any

import pytest
from pydantic import ValidationError

from app.ai.llm import gateway
from app.ai.llm.gateway import ResolvedAiModel
from app.core.config import Settings
from app.core.errors import ValidationFailedError
from app.modules.resume.optimization import Selection


def _config(**overrides: Any) -> ResolvedAiModel:
    """构造默认请求配置，允许局部覆盖。"""
    values: dict[str, Any] = {
        "base_url": "https://example.test/v1",
        "remote_model_id": "model-x",
        "api_key": "secret",
    }
    values.update(overrides)
    return ResolvedAiModel(**values)


def _settings() -> Settings:
    """返回固定超时的测试配置，不读取 .env。"""
    return Settings(ai_timeout_seconds=30, _env_file=None)  # pyright: ignore[reportCallIssue]


class _UpstreamHTTPError(urllib.error.URLError):
    """模拟带状态码的上游错误（非 2xx 或重定向）。

    真实 `urllib.error.HTTPError` 会创建临时文件并在回收时发出 ResourceWarning，
    而本项目把警告视为错误；网关对 `URLError` 与其子类 `HTTPError` 的处理完全一致
    （都映射为同一个安全错误），因此用带 `code` 的 `URLError` 子类替代即可。
    """

    def __init__(self, status: int) -> None:
        """记录 HTTP 状态码，便于断言触发的是对应分支。"""
        super().__init__(f"HTTP {status}")
        self.code = status


class _FakeResponse:
    """可当上下文管理器使用的受控响应。"""

    def __init__(self, body: bytes) -> None:
        """保存待返回的响应体。"""
        self._body = body

    def read(self, size: int) -> bytes:
        """返回响应体；忽略大小参数，由调用方自行判断超限。"""
        return self._body

    def __enter__(self) -> _FakeResponse:
        """进入上下文。"""
        return self

    def __exit__(self, *args: object) -> None:
        """退出上下文，不做额外处理。"""
        return None


class _CapturingOpener:
    """捕获请求细节，并用受控响应替代真实网络。"""

    def __init__(self, captured: dict[str, Any], response: bytes | Exception) -> None:
        """保存捕获容器与待返回的响应或异常。"""
        self._captured = captured
        self._response = response

    def open(self, request: Any, timeout: float) -> Any:
        """记录请求后返回受控响应，或抛出预设异常。"""
        self._captured["url"] = request.full_url
        self._captured["headers"] = dict(request.header_items())
        self._captured["body"] = json.loads(request.data.decode()) if request.data else None
        self._captured["timeout"] = timeout
        self._captured["calls"] = self._captured.get("calls", 0) + 1
        if isinstance(self._response, Exception):
            raise self._response
        return _FakeResponse(self._response)


def _install_opener(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any], response: bytes | Exception) -> None:
    """安装受控 opener 与固定超时配置。"""

    def opener(*handlers: Any) -> _CapturingOpener:
        """忽略真实处理器，返回捕获替身。"""
        return _CapturingOpener(captured, response)

    monkeypatch.setattr(gateway.urllib.request, "build_opener", opener)
    monkeypatch.setattr(gateway, "get_settings", _settings)


def test_gateway_posts_openai_compatible_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """请求应是 OpenAI 兼容的 chat completions，并携带模型标识与鉴权头。"""
    captured: dict[str, Any] = {}
    body = json.dumps({"choices": [{"message": {"content": json.dumps({"ok": True})}}]}).encode()
    _install_opener(monkeypatch, captured, body)

    result = asyncio.run(gateway.generate(_config(), "jd_requirements", {"field": "value"}, {"type": "object"}))

    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["body"]["model"] == "model-x"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert result == {"ok": True}


def test_gateway_omits_authorization_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置凭据时不得发送空的 Authorization 头。"""
    captured: dict[str, Any] = {}
    body = json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()
    _install_opener(monkeypatch, captured, body)

    asyncio.run(gateway.generate(_config(api_key=None), "task", {}, {}))

    assert "Authorization" not in captured["headers"]


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.com/v1",
        "https://user:pass@example.com/v1",
        "https://example.com/v1?tenant=1",
        "https://example.com/v1#section",
        "ftp://example.com/v1",
        "",
    ],
)
def test_gateway_rejects_unsafe_base_url(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    """地址不安全时在发起请求前拒绝。"""

    def no_network(*handlers: Any) -> Any:
        """命中即表示不应该发起网络请求。"""
        raise AssertionError("不应发起请求")

    monkeypatch.setattr(gateway.urllib.request, "build_opener", no_network)

    with pytest.raises(ValidationFailedError):
        asyncio.run(gateway.generate(_config(base_url=base_url), "task", {}, {}))


def test_gateway_timeout_is_safe_and_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """超时只调用一次，且异常文案不包含上游原文。"""
    captured: dict[str, Any] = {}
    _install_opener(monkeypatch, captured, TimeoutError("private-upstream-token"))

    with pytest.raises(ValidationFailedError) as error:
        asyncio.run(gateway.generate(_config(), "task", {}, {}))

    assert "private-upstream-token" not in str(error.value)
    assert captured["calls"] == 1
    assert captured["timeout"] == 30


@pytest.mark.parametrize("status", [400, 401, 500])
def test_gateway_maps_non_2xx_to_safe_error(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    """非 2xx 不泄漏上游错误正文。"""
    captured: dict[str, Any] = {}
    _install_opener(monkeypatch, captured, _UpstreamHTTPError(status))

    with pytest.raises(ValidationFailedError) as error:
        asyncio.run(gateway.generate(_config(), "task", {}, {}))

    assert "boom" not in str(error.value)


def test_gateway_rejects_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """拒绝重定向响应，不向新地址转发数据。"""
    captured: dict[str, Any] = {}
    _install_opener(monkeypatch, captured, _UpstreamHTTPError(302))

    with pytest.raises(ValidationFailedError):
        asyncio.run(gateway.generate(_config(), "task", {}, {}))


def test_gateway_rejects_non_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """响应不是 JSON 对象时安全失败。"""
    captured: dict[str, Any] = {}
    _install_opener(monkeypatch, captured, b"not-json")

    with pytest.raises(ValidationFailedError):
        asyncio.run(gateway.generate(_config(), "task", {}, {}))


def test_gateway_rejects_oversize_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """响应超过 1 MB 时安全失败，避免占用大量内存。"""
    captured: dict[str, Any] = {}
    _install_opener(monkeypatch, captured, b"{" + b" " * 1_000_001 + b"}")

    with pytest.raises(ValidationFailedError):
        asyncio.run(gateway.generate(_config(), "task", {}, {}))


# 显式标注为 object：参数化字面量里含空 dict，推断类型会带未知部分。
_INVALID_CONTENT_RESPONSES: list[object] = [
    {"choices": []},
    {"choices": [{"message": {}}]},
    {"choices": [{"message": {"content": ""}}]},
    {"choices": [{"message": {"content": "not-json"}}]},
    {"choices": "invalid"},
]


@pytest.mark.parametrize("payload", _INVALID_CONTENT_RESPONSES)
def test_gateway_rejects_missing_or_invalid_content(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    """缺少 `choices[0].message.content` 或内容不是 JSON 时安全失败。"""
    captured: dict[str, Any] = {}
    _install_opener(monkeypatch, captured, json.dumps(payload).encode())

    with pytest.raises(ValidationFailedError):
        asyncio.run(gateway.generate(_config(), "task", {}, {}))


def test_connection_test_sends_only_a_minimal_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    """连接测试只发送固定 ping 与 max_tokens=1，不携带任何业务数据。"""
    captured: dict[str, Any] = {}
    body = json.dumps({"choices": [{"message": {"content": ""}}]}).encode()
    _install_opener(monkeypatch, captured, body)

    asyncio.run(gateway.check_connection(_config()))

    assert captured["body"]["max_tokens"] == 1
    assert captured["body"]["messages"] == [{"role": "user", "content": "ping"}]
    assert "input" not in captured["body"]


def test_connection_test_requires_compatible_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """连接测试返回不兼容内容时同样安全失败。"""
    captured: dict[str, Any] = {}
    _install_opener(monkeypatch, captured, json.dumps({"choices": []}).encode())

    with pytest.raises(ValidationFailedError):
        asyncio.run(gateway.check_connection(_config()))


@pytest.mark.parametrize("index", [True, "0", 0.0])
def test_selection_requires_real_integer_indices(index: object) -> None:
    """布尔、字符串和浮点数不能被隐式强转成条目索引。"""
    with pytest.raises(ValidationError):
        Selection.model_validate(
            {
                "experiences": [],
                "projects": [],
                "skills": [index],
                "educations": [],
                "languages": [],
            }
        )
