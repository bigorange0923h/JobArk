"""最小独立搜索适配契约；仅向配置端点发送公司身份，不读取任意网页 URL。"""

import asyncio
import http.client
import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.core.config import Settings


class SearchFailure(Exception):
    """只携带稳定安全状态，禁止透传上游正文或令牌。"""

    def __init__(self, status: str) -> None:
        """保存未配置/不支持/超时/失败类型，不包含业务原文。"""
        self.status = status
        super().__init__(status)


class SearchSource(BaseModel):
    """服务商返回的必要摘录；不视为独立核实的公司事实。"""

    model_config = ConfigDict(extra="forbid")
    url: HttpUrl
    title: str = Field(min_length=1, max_length=400)
    excerpt: str = Field(min_length=1, max_length=5000)
    published_at: str | None = Field(default=None, max_length=100)


class SearchResponse(BaseModel):
    """独立适配器协议；未支持能力不能以聊天模型自述代替。"""

    model_config = ConfigDict(extra="forbid")
    sources: list[SearchSource] = Field(max_length=8)
    partial: bool = False


def public_url(url: str) -> str:
    """校验公开 HTTPS 地址；禁止凭据、私有/保留 IP、危险端口及本地名称。

    本函数不获取正文。外部请求仅发生于显式配置的搜索端点；该端点还须 DNS 校验。
    """
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("unsafe URL")
    host = parsed.hostname.casefold()
    if host in {"localhost", "metadata.google.internal"} or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("unsafe host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return url
    if not address.is_global:
        raise ValueError("private address")
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """不跟随搜索端点重定向，防止身份与令牌外泄。"""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        """拒绝所有重定向。"""
        return None


class PinnedConnection(http.client.HTTPSConnection):
    """连接已校验 IP，并保留原 hostname 的 TLS 验证，避免 DNS 二次解析重绑定。"""

    def __init__(self, host: str, address: str, **kwargs: Any) -> None:
        """固定公开地址；TLS SNI 与证书校验仍使用配置端点域名。"""
        self.tls_context = ssl.create_default_context()
        super().__init__(host, context=self.tls_context, **kwargs)
        self.address = address

    def connect(self) -> None:
        """只连接固定 IP，不走代理或重定向。"""
        connection = socket.create_connection((self.address, 443), self.timeout)
        self.sock = self.tls_context.wrap_socket(connection, server_hostname=self.host)


class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """只为当前搜索请求使用已校验的公开 IP。"""

    def __init__(self, address: str) -> None:
        """固定本请求的连接地址，不缓存 DNS 或来源正文。"""
        super().__init__()
        self.address = address

    def https_open(self, req: urllib.request.Request) -> Any:
        """保留 urllib 响应/错误语义并固定连接地址。"""

        def connection(host: str, **kwargs: Any) -> PinnedConnection:
            """向 urllib 提供类型明确的固定 IP 连接工厂。"""
            return PinnedConnection(host, self.address, **kwargs)

        return self.do_open(connection, req)


def _search(settings: Settings, identity: dict[str, str], query: str) -> SearchResponse:
    """受限 POST 搜索协议；无重试、响应 1MB 上限和单请求预算。

    不安装或假设具体付费搜索服务。端点必须实现 {identity,query,limit} → sources 协议。
    地址固定为管理员配置，不由网页或模型提供；禁止代理环境改变请求路由。
    """
    if not settings.company_search_url:
        raise SearchFailure("NOT_CONFIGURED")
    try:
        endpoint = public_url(settings.company_search_url)
        parsed = urlsplit(endpoint)
        if parsed.query or parsed.fragment:
            raise ValueError("endpoint query")
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError("private DNS")
        headers = {"Content-Type": "application/json"}
        if settings.company_search_token.get_secret_value():
            headers["Authorization"] = f"Bearer {settings.company_search_token.get_secret_value()}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(
                {"identity": identity, "query": query, "limit": settings.company_search_sources}, ensure_ascii=False
            ).encode(),
            headers=headers,
            method="POST",
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(), PinnedHTTPSHandler(str(addresses[0][4][0]))
        )
        with opener.open(request, timeout=settings.company_search_timeout) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("oversize")
        return SearchResponse.model_validate_json(raw)
    except urllib.error.HTTPError as error:
        raise SearchFailure("UNSUPPORTED" if error.code in (404, 405, 501) else "FAILED") from error
    except TimeoutError as error:
        raise SearchFailure("TIMEOUT") from error
    except (ValueError, OSError, urllib.error.URLError) as error:
        raise SearchFailure("FAILED") from error


async def search(settings: Settings, identity: dict[str, str], query: str) -> SearchResponse:
    """在线程执行固定端点搜索；调用方必须释放数据库事务。"""
    return await asyncio.to_thread(_search, settings, identity, query)
