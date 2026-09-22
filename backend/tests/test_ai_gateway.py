"""网关地址、超时、输出类型及无重试边界；测试不访问网络。"""

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from app.ai.llm import gateway
from app.core.config import Settings
from app.core.errors import ConflictError, ValidationFailedError
from app.modules.resume.optimization import Selection


@pytest.mark.parametrize("url", ["", "http://example.com", "http://localhost:80@example.com/path"])
def test_gateway_rejects_unsafe_or_missing_address(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """地址未配置或用凭据伪装回环地址时，请求前拒绝。"""
    monkeypatch.setattr(gateway, "get_settings", lambda: Settings(ai_gateway_url=url))
    with pytest.raises(ConflictError):
        asyncio.run(gateway.generate("test", {}, {}))


def test_timeout_is_safe_and_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """上游错误不得泄漏响应，超时只调用一次。"""
    calls: list[float] = []

    class FakeOpener:
        """模拟不可用网关，不建立网络连接。"""

        def open(self, request: Any, timeout: float) -> Any:
            """记录超时并模拟带敏感信息的异常。"""
            calls.append(timeout)
            raise TimeoutError("private-upstream-token")

    monkeypatch.setattr(gateway, "get_settings", lambda: Settings(ai_gateway_url="https://example.com"))

    def opener(*handlers: Any) -> FakeOpener:
        """返回受控替身，忽略真实处理器。"""
        return FakeOpener()

    monkeypatch.setattr(gateway.urllib.request, "build_opener", opener)
    with pytest.raises(ValidationFailedError) as error:
        asyncio.run(gateway.generate("test", {}, {}))
    assert "private-upstream-token" not in str(error.value)
    assert calls == [30]


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
