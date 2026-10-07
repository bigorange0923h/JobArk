"""公司尽调的来源绑定、协议、失败与预算替身测试，不访问真实搜索服务。"""

from typing import Any

import pytest

from app.core.config import Settings
from app.core.errors import ValidationFailedError
from app.modules.job import research
from app.modules.job.research import Findings, bind_sources, validate_findings
from app.modules.job.research_adapter import SearchFailure, SearchResponse, SearchSource, public_url


def source(url: str = "https://acme.example/about", excerpt: str = "甲科技：产品平台") -> SearchSource:
    """构造无真人资料、可核对的搜索替身来源。"""
    return SearchSource.model_validate({"url": url, "title": "公开页面", "excerpt": excerpt})


def test_entity_binding_duplicates_and_unsafe_urls() -> None:
    """同名不自动归属，重复转载摘录只算一次，私有 URL 不进入报告。"""
    identity = {"legal_name": "甲科技", "website_url": "https://acme.example", "city": "杭州"}
    sources, rejected = bind_sources(
        [
            source(),
            source("https://copy.example/a"),
            source("https://news.example/b", "甲科技：北京招聘"),
            source("https://127.0.0.1/a"),
        ],
        identity,
        8,
    )
    assert len(sources) == 1
    assert sources[0]["source_type"] == "OFFICIAL"
    assert rejected == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.0.0.1",
        "https://169.254.169.254",
        "https://[::1]",
        "https://user:password@example.com",
        "https://example.com:444",
    ],
)
def test_public_url_rejects_ssrf(url: str) -> None:
    """非法方案、私有地址、凭据和端口在请求前拒绝。"""
    with pytest.raises(ValueError):
        public_url(url)


def test_summary_cannot_fabricate_sources_or_certify_anonymous_reviews() -> None:
    """模型不能凭空引用、执行网页提示注入或将普通网页变成核实事实。"""
    finding = {
        "dimension": "RISK",
        "kind": "FACT",
        "text": "来源称发生风险",
        "source_ids": ["s0"],
        "quotes": ["公开线索"],
        "stance": "SUPPORT",
        "confidence_reason": "需要核对",
    }
    with pytest.raises(ValidationFailedError):
        validate_findings(Findings.model_validate({"findings": [finding]}), [])
    with pytest.raises(ValidationFailedError):
        validate_findings(
            Findings.model_validate({"findings": [finding]}),
            [{"id": "s0", "excerpt": "公开线索", "source_type": "WEB_CLUE"}],
        )
    result = validate_findings(
        Findings.model_validate({"findings": [{**finding, "kind": "OPINION"}]}),
        [{"id": "s0", "excerpt": "公开线索", "source_type": "WEB_CLUE"}],
    )
    assert len(result) == 5
    assert result[-1]["kind"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_no_search_configuration_is_not_a_positive_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有真实能力时不调用聊天模型伪装搜索。"""
    settings = Settings(company_search_url="", _env_file=None)  # pyright: ignore[reportCallIssue]
    monkeypatch.setattr(research, "get_settings", lambda: settings)
    status, report = await research.collect({"legal_name": "甲科技"})
    assert status == "NOT_CONFIGURED" and not report["sources"]


@pytest.mark.asyncio
async def test_partial_timeout_retains_sources_and_sends_only_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """后续搜索失败不丢已验证来源，查询不携带个人资料或整段 JD。"""
    settings = Settings(company_search_url="https://search.example/api", _env_file=None)  # pyright: ignore[reportCallIssue]
    monkeypatch.setattr(research, "get_settings", lambda: settings)
    calls: list[dict[str, Any]] = []

    async def fake_search(settings: Settings, identity: dict[str, str], query: str) -> SearchResponse:
        """第一轮返回来源，其余模拟超时，无真实网络。"""
        calls.append({"identity": identity, "query": query})
        if len(calls) == 1:
            return SearchResponse(sources=[source()])
        raise SearchFailure("TIMEOUT")

    monkeypatch.setattr(research, "search", fake_search)
    status, report = await research.collect(
        {"legal_name": "甲科技", "website_url": "https://acme.example", "city": "杭州"}
    )
    assert status == "PARTIAL" and len(report["sources"]) == 1
    assert len(calls) == 6
    assert set(calls[0]["identity"]) == {"legal_name", "website_url", "city"}
