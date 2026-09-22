"""可配置 JSON 推理网关；只接受固定任务，调用前由应用服务结束事务。"""

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any, cast
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.core.errors import ConflictError, ValidationFailedError


def _request(task: str, input_data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """向配置的网关发送一次请求；禁止重定向，失败不自动重试。"""
    settings = get_settings()
    if not settings.ai_gateway_url:
        raise ConflictError("尚未配置 AI 网关，请配置后再使用 AI 功能。")
    address = urlsplit(settings.ai_gateway_url)
    if (
        not address.hostname
        or address.username is not None
        or address.password is not None
        or not (
            address.scheme == "https"
            or (address.scheme == "http" and address.hostname in {"localhost", "127.0.0.1", "::1"})
        )
    ):
        raise ConflictError("AI 网关必须使用 HTTPS 或本地回环地址。")
    headers = {"Content-Type": "application/json"}
    if settings.ai_gateway_token.get_secret_value():
        headers["Authorization"] = f"Bearer {settings.ai_gateway_token.get_secret_value()}"
    request = urllib.request.Request(
        settings.ai_gateway_url,
        data=json.dumps({"task": task, "input": input_data, "output_schema": schema}, ensure_ascii=False).encode(),
        headers=headers,
        method="POST",
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        """避免网关重定向将输入或令牌转发到其他站点。"""

        def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
            """拒绝所有重定向，不向新地址发送数据。"""
            return None

    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=settings.ai_timeout_seconds) as response:
            body = response.read(1_000_001)
        if len(body) > 1_000_000:
            raise ValueError("oversize")
        result: Any = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError("invalid envelope")
        return cast(dict[str, Any], result)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        raise ValidationFailedError("AI 请求失败或结果无效，原始资料已保留，请稍后手动重试。") from error


async def generate(task: str, input_data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """在线程中执行有超时的一次网关请求，返回待验证 JSON，不写业务事实。"""
    return await asyncio.to_thread(_request, task, input_data, schema)
