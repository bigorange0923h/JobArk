"""受限 LLM 网关：固定任务、Schema、超时、禁止重定向且不自动重试。

外部 HTTP 集中在适配层：领域模块只提交已解析的请求配置与结构化输入，由本模块负责
地址校验、请求构造、响应大小限制与安全错误映射。所有调用都在工作线程中执行，
调用方必须在等待网络之前结束数据库事务（见 ADR 0002），避免长事务占用连接。
"""

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.core.errors import ValidationFailedError

# 响应体上限：防止上游返回超大内容占满内存。读取时多读 1 字节，用于判断是否超限。
_MAX_RESPONSE_BYTES = 1_000_000
# 只有本地回环允许明文 HTTP；其余地址必须 HTTPS，避免凭据与资料在明文连接上传输。
_LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class ResolvedAiModel:
    """已解析的模型请求配置。

    只存在于内存，不写数据库也不进日志：`api_key` 是解密后的明文，用完即弃，
    避免凭据在进程内被长期持有或被序列化。
    """

    base_url: str
    remote_model_id: str
    api_key: str | None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """拒绝所有重定向，避免把输入或凭据转发到其他站点。"""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        """返回 None 表示不跟随重定向，也不会向新地址发送数据。"""
        return None


def validate_base_url(base_url: str) -> str:
    """校验并规范化服务商基地址。

    参数:
        base_url: 用户提交的 OpenAI 兼容接口基地址。

    返回:
        str: 去掉末尾斜杠的基地址，供拼接 `/chat/completions`。

    异常:
        ValidationFailedError: 非 HTTPS、非本地回环 HTTP，或含凭据、查询参数、片段。
    """
    address = urlsplit(base_url)
    if (
        not address.hostname
        or address.username is not None
        or address.password is not None
        or address.query
        or address.fragment
        or not (address.scheme == "https" or (address.scheme == "http" and address.hostname in _LOCAL_HOSTNAMES))
    ):
        raise ValidationFailedError(
            "AI 服务商地址必须使用 HTTPS 或本地回环 HTTP，且不能包含用户名、密码、查询参数或片段。"
        )
    return base_url.rstrip("/")


def _post_chat(config: ResolvedAiModel, body: dict[str, Any]) -> dict[str, Any]:
    """向 OpenAI 兼容接口发送一次受限的 JSON 请求。

    参数:
        config: 已解析的请求配置，含基地址、模型标识与可选明文 Key。
        body: 请求体。

    返回:
        dict[str, Any]: 解析后的 JSON 对象。

    异常:
        ValidationFailedError: 地址不安全、上游错误、超时、响应超限或响应不是 JSON 对象。

    注意:
        不自动重试：外部副作用不能因不确定重试而重复提交；只有配置了 Key 时才发送
        `Authorization`，避免向本地服务发送空凭据。
    """
    endpoint = f"{validate_base_url(config.base_url)}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=get_settings().ai_timeout_seconds) as (
            response
        ):
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ValueError("oversize")
        parsed: Any = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("invalid envelope")
        return cast(dict[str, Any], parsed)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        # 不把上游原文或凭据带进异常：响应体可能包含敏感信息，异常文案会进入 API 响应。
        raise ValidationFailedError("AI 请求失败或结果无效，原始资料已保留，请稍后手动重试。") from error


def _has_chat_choices(response: dict[str, Any]) -> bool:
    """判断响应是否含可供连接测试确认的 OpenAI 兼容首条消息。

    连接测试不要求模型输出非空内容（`max_tokens=1` 时空字符串仍可能合法），但必须
    验证实际生成依赖的 `choices[0].message.content` 结构，避免把不兼容响应误报为成功。
    """
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = cast("list[object]", choices)[0]
    if not isinstance(first, dict):
        return False
    message = cast("dict[str, object]", first).get("message")
    return isinstance(message, dict) and isinstance(cast("dict[str, object]", message).get("content"), str)


async def check_connection(config: ResolvedAiModel) -> None:
    """发送一次最小协议请求验证连通性。

    参数:
        config: 已解析的请求配置。

    异常:
        ValidationFailedError: 上游不可用或响应不符合 OpenAI 兼容格式。

    注意:
        只发送固定 ping 与 `max_tokens=1`，不携带简历、档案、职位或匹配数据，
        因此不会产生业务事实，也不会把用户内容发往外部。
    """
    body = {
        "model": config.remote_model_id,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    response = await asyncio.to_thread(_post_chat, config, body)
    if not _has_chat_choices(response):
        raise ValidationFailedError("AI 服务返回的内容不符合 OpenAI 兼容格式。")


def _extract_message_content(response: dict[str, Any]) -> str:
    """从 OpenAI 兼容响应中取出 `choices[0].message.content` 字符串。

    参数:
        response: 上游返回的 JSON 对象。

    返回:
        str: 模型输出的文本内容；调用方还需按业务 Schema 二次校验。

    异常:
        ValidationFailedError: 缺少 `choices`、`message` 或文本内容时抛出安全错误。

    注意:
        只接受字符串内容：有些兼容实现会返回结构化数组或对象，那些形态无法与
        "模型必须输出 JSON 文本"的既有契约对齐，宁可安全失败也不做猜测解析。
    """
    raw_choices = response.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        raise ValidationFailedError("AI 服务返回的内容不符合 OpenAI 兼容格式。")
    first = cast("list[object]", raw_choices)[0]
    if not isinstance(first, dict):
        raise ValidationFailedError("AI 服务返回的内容不符合 OpenAI 兼容格式。")
    message = cast("dict[str, object]", first).get("message")
    if not isinstance(message, dict):
        raise ValidationFailedError("AI 服务返回的内容不符合 OpenAI 兼容格式。")
    content = cast("dict[str, object]", message).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValidationFailedError("AI 服务返回的内容不符合 OpenAI 兼容格式。")
    return content


async def generate(
    config: ResolvedAiModel, task: str, input_data: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    """向默认模型发送一次受限的 OpenAI 兼容结构化请求，不写业务事实。

    参数:
        config: 已解析的默认模型请求配置（基地址、远端模型标识与明文凭据）。
        task: 固定任务名，写入系统消息，便于上游按用途区分。
        input_data: 任务输入；只应包含已获用户同意发送的内容。
        schema: 期望的输出 JSON Schema。

    返回:
        dict[str, Any]: 模型返回的 JSON 对象；**尚未**按业务 Schema 校验。

    异常:
        ValidationFailedError: 地址不安全、上游错误、超时、响应超限、非 JSON 或缺少内容。

    注意:
        请求体包含 `response_format={"type": "json_object"}` 与一个 JSON 用户消息；
        不自动重试，调用方必须在等待本协程前结束数据库事务。
    """
    body = {
        "model": config.remote_model_id,
        "messages": [
            {
                "role": "system",
                "content": f"你是受控的 JSON 服务，任务标识为 {task}。只返回一个 JSON 对象，不要输出解释或额外文本。",
            },
            {
                "role": "user",
                "content": json.dumps({"input": input_data, "output_schema": schema}, ensure_ascii=False),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    response = await asyncio.to_thread(_post_chat, config, body)
    content = _extract_message_content(response)
    try:
        parsed: Any = json.loads(content)
    except (TypeError, ValueError) as error:
        raise ValidationFailedError("AI 返回的内容不是有效 JSON，原始资料已保留，请稍后手动重试。") from error
    if not isinstance(parsed, dict):
        raise ValidationFailedError("AI 返回的 JSON 不是对象，原始资料已保留，请稍后手动重试。")
    return cast(dict[str, Any], parsed)
