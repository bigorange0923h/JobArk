"""招聘页面适配器的纯本地样例回归，不代表四站网络或实时 DOM 已验证。"""

from __future__ import annotations

import json

import pytest

from app.automation.adapters.job_pages import extract_job, identify_posting
from app.core.errors import ValidationFailedError
from app.modules.job.enums import JobSource

_LINKEDIN = "https://www.linkedin.com/jobs/view/1234567890/"
_INDEED = "https://www.indeed.com/viewjob?jk=0123456789abcdef"
_BOSS = "https://www.zhipin.com/job_detail/0123456789abcdef.html"
_FIFTYONEJOB = "https://jobs.51job.com/shanghai/123456789.html"


def _job(url: str = _LINKEDIN) -> dict[str, object]:
    """构造单个职位的必要 JSON-LD 字段，不包含个人或账户信息。"""
    return {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "url": url,
        "title": "后端工程师",
        "hiringOrganization": {"@type": "Organization", "name": "示例科技"},
        "jobLocation": {"@type": "Place", "address": {"addressLocality": "上海", "addressRegion": "上海市"}},
        "description": "<p>负责后端服务设计。</p><ul><li>熟悉 Python。</li><li>具备数据库经验。</li></ul>",
    }


def _html(payload: object) -> str:
    """构造带导航和无关脚本的页面，供本地解析验证。"""
    script = json.dumps(payload, ensure_ascii=False)
    return (
        '<html><head><title>招聘站 - 不应作为职位标题</title><script type="application/ld+json">'
        f'{script}</script></head><body><nav>海量职位导航</nav><script>window.secret="不要保存";</script>'
        "<main>页面展示正文</main></body></html>"
    )


@pytest.mark.parametrize(
    ("url", "source", "identifier", "canonical"),
    [
        (_LINKEDIN + "?trackingId=removed#top", JobSource.LINKEDIN, "1234567890", _LINKEDIN),
        (
            "https://cn.linkedin.com/jobs/view/backend-engineer-1234567890?trk=test",
            JobSource.LINKEDIN,
            "1234567890",
            _LINKEDIN,
        ),
        (_INDEED + "&from=removed#top", JobSource.INDEED, "0123456789abcdef", _INDEED),
        (
            "https://indeed.com:443/viewjob?vjk=ignored&jk=0123456789ABCDEF",
            JobSource.INDEED,
            "0123456789abcdef",
            _INDEED,
        ),
        (_BOSS + "?ka=removed", JobSource.BOSS, "0123456789abcdef", _BOSS),
        (
            "https://www.zhipin.com/job_detail/29ded4250a3b63561XR_2tS-E1NR~~.html",
            JobSource.BOSS,
            "29ded4250a3b63561XR_2tS-E1NR~~",
            "https://www.zhipin.com/job_detail/29ded4250a3b63561XR_2tS-E1NR~~.html",
        ),
        (_FIFTYONEJOB + "?s=removed#top", JobSource.FIFTYONEJOB, "123456789", _FIFTYONEJOB),
    ],
)
def test_four_platform_detail_urls_have_stable_identity(
    url: str,
    source: JobSource,
    identifier: str,
    canonical: str,
) -> None:
    """平台 ID 与规范链接剔除跟踪参数，保留必要的 Indeed jk。"""
    identity = identify_posting(url)
    assert identity.source == source
    assert identity.external_id == identifier
    assert identity.canonical_url == canonical


@pytest.mark.parametrize(
    "url",
    [
        "http://www.linkedin.com/jobs/view/1234567890",
        "https://user:password@www.linkedin.com/jobs/view/1234567890",
        "https://@www.linkedin.com/jobs/view/1234567890",
        "https://www.linkedin.com:8443/jobs/view/1234567890",
        "https://www.linkedin.com:wrong/jobs/view/1234567890",
        "https://www.linkedin.com.evil.test/jobs/view/1234567890",
        "https://evil-linkedin.com/jobs/view/1234567890",
        "https://www.linkedin.com/jobs/search/?keywords=Python",
        "https://www.linkedin.com/jobs/view/abc",
        "https://www.linkedin.com/jobs/view/123%2F456",
        "https://www.linkedin.com/jobs/view/1234567890\n?secret=test",
        "https://www.indeed.com/jobs?q=python",
        "https://www.indeed.com/viewjob?jk=0123456789abcdef&jk=fedcba9876543210",
        "https://www.indeed.com/viewjob?jk=0123456789abcdef&jk=",
        "https://www.indeed.com/viewjob?jk=invalid",
        "https://www.zhipin.com/web/geek/job?query=python",
        "https://www.zhipin.com/job_detail/.html",
        "https://www.zhipin.com/job_detail/12345678.html/extra",
        "https://jobs.51job.com/",
        "https://jobs.51job.com/shanghai/abc.html",
        "https://we.51job.com/pc/search?keyword=python",
        "https://127.0.0.1/jobs/view/1234567890",
        "file:///jobs/view/1234567890",
    ],
)
def test_invalid_urls_fail_without_visiting_them(url: str) -> None:
    """凭据、伪造域名、列表和不支持的详情形态都返回字段级 422。"""
    with pytest.raises(ValidationFailedError) as caught:
        identify_posting(url)
    assert caught.value.status_code == 422
    assert caught.value.details[0].field == "url"


@pytest.mark.parametrize("url", [_LINKEDIN, _INDEED, _BOSS, _FIFTYONEJOB])
def test_single_jobposting_extracts_only_necessary_fields(url: str) -> None:
    """同一结构契约适用于四站本地样例，不保存整页或脚本。"""
    result = extract_job(_html(_job(url)), "HTML", identify_posting(url))
    assert result.company_name == "示例科技"
    assert result.title == "后端工程师"
    assert result.location == "上海市 上海"
    assert result.raw_jd == "负责后端服务设计。\n熟悉 Python。\n具备数据库经验。"
    assert "secret" not in result.raw_jd
    assert "导航" not in result.raw_jd
    assert result.extractor_version == "local-job-page-v1"


@pytest.mark.parametrize(
    "payload",
    [
        [_job(), {"@type": "BreadcrumbList"}],
        {"@graph": [{"@type": "WebPage"}, _job()]},
        {"@graph": {"@type": ["Thing", "JobPosting"], **_job()}},
    ],
)
def test_jobposting_in_array_or_graph_is_supported(payload: object) -> None:
    """数组和图包含恰好一个职位时采用该结构。"""
    result = extract_job(_html(payload), "HTML", identify_posting(_LINKEDIN))
    assert result.title == "后端工程师"


@pytest.mark.parametrize("payload", [[_job(), _job()], {"@graph": [_job(), _job(_INDEED)]}])
def test_multiple_jobs_cannot_be_silently_joined(payload: object) -> None:
    """即使两个对象字段相同也不自行判定重复，而要求单职位正文。"""
    with pytest.raises(ValidationFailedError, match="多个职位"):
        extract_job(_html(payload), "HTML", identify_posting(_LINKEDIN))


@pytest.mark.parametrize("payload", [None, 1, "JobPosting", {"@graph": "invalid"}])
def test_invalid_jsonld_topology_is_rejected(payload: object) -> None:
    """错误结构不能降级为看似成功的可靠结构提取。"""
    with pytest.raises(ValidationFailedError):
        extract_job(_html(payload), "HTML", identify_posting(_LINKEDIN))


@pytest.mark.parametrize("script", ['{"@type": "JobPosting",', '{"value": NaN}', '{"value": Infinity}'])
def test_damaged_or_nonstandard_jsonld_is_rejected(script: str) -> None:
    """解析错误不带上原文，非标准数字不能混入候选。"""
    with pytest.raises(ValidationFailedError):
        extract_job(
            f'<script type="application/ld+json">{script}</script><p>正文</p>',
            "HTML",
            identify_posting(_LINKEDIN),
        )


def test_duplicate_json_fields_cannot_ambiguously_select_job_content() -> None:
    """重复键不是可靠结构，不能默默选择最后一个来源或描述。"""
    script = '{"@type":"JobPosting","description":"A","description":"B"}'
    with pytest.raises(ValidationFailedError, match="重复字段"):
        extract_job(f'<script type="application/ld+json">{script}</script>', "HTML", identify_posting(_LINKEDIN))


def test_unclosed_jsonld_is_not_downgraded_to_visible_text() -> None:
    """已看到结构脚本但内容未闭合时，不误称缺少结构且解析成功。"""
    html = '<main>负责后端开发。</main><script type="application/ld+json">{"@type":"JobPosting"}'
    with pytest.raises(ValidationFailedError, match="未完整闭合"):
        extract_job(html, "HTML", identify_posting(_LINKEDIN))


@pytest.mark.parametrize(
    ("field", "value"),
    [("title", 123), ("hiringOrganization", ["公司"]), ("description", {"text": "正文"}), ("jobLocation", "上海")],
)
def test_malformed_necessary_fields_are_not_stringified(field: str, value: object) -> None:
    """类型错误安全失败，不能把字典或数组转成职位事实。"""
    payload = _job()
    payload[field] = value
    with pytest.raises(ValidationFailedError):
        extract_job(_html(payload), "HTML", identify_posting(_LINKEDIN))


def test_missing_company_title_and_location_remain_empty() -> None:
    """网页 title 不作为职位标题，缺失结构字段留给人工填写。"""
    payload = {"@type": "JobPosting", "description": "负责后端服务设计与维护。"}
    result = extract_job(_html(payload), "HTML", identify_posting(_LINKEDIN))
    assert result.company_name == ""
    assert result.title == ""
    assert result.location is None
    assert any("公司" in warning for warning in result.warnings)
    assert any("标题" in warning for warning in result.warnings)


def test_html_without_schema_keeps_body_and_requires_human_fields() -> None:
    """无可靠结构时保留可见正文，剔除脚本、表单、导航和隐藏节点。"""
    html = (
        "<html><head><title>职位名不可推断</title><style>.hidden{display:none}</style></head>"
        "<body><header>站点页头</header><nav>职位导航</nav><main><h2>职责</h2><p>开发 Python 服务。</p>"
        '<script>window.Cookie="private";</script><div hidden>隐藏秘密</div>'
        '<div style="display: none">隐藏内容</div><span aria-hidden="true">隐藏字符</span>'
        "<form><label>密码字段</label><input value='secret'></form></main><footer>版权</footer></body></html>"
    )
    result = extract_job(html, "HTML", identify_posting(_LINKEDIN))
    assert result.raw_jd == "职责\n开发 Python 服务。"
    assert result.company_name == ""
    assert result.title == ""
    assert "未找到可靠的职位结构" in result.warnings[0]


def test_text_mode_preserves_user_body_without_claiming_structure_extraction() -> None:
    """纯文本只保留用户正文及人工填写提示。"""
    result = extract_job("  职位描述\n负责后端服务。\n  ", "TEXT", identify_posting(_BOSS))
    assert result.raw_jd == "职位描述\n负责后端服务。"
    assert result.title == ""
    assert result.company_name == ""
    assert "用户提供的正文" in result.warnings[0]


@pytest.mark.parametrize(
    "html",
    ["", "<script>window.secret='private';</script>", "<form>请登录</form>", "<h1>请完成验证</h1>", "<h1>登录</h1>"],
)
def test_empty_login_and_verification_pages_fail(html: str) -> None:
    """登录、验证或纯框架页不生成职位候选。"""
    with pytest.raises(ValidationFailedError):
        extract_job(html, "HTML", identify_posting(_LINKEDIN))


@pytest.mark.parametrize("description", [None, "", "  ", "<script>alert('x')</script>", "<style>p{}</style>"])
def test_jobposting_requires_nonempty_description(description: object) -> None:
    """存在职位对象也不能用其他页面文本替代其缺失的描述。"""
    payload = _job()
    payload["description"] = description
    with pytest.raises(ValidationFailedError):
        extract_job(_html(payload), "HTML", identify_posting(_LINKEDIN))


@pytest.mark.parametrize("field", ["url", "mainEntityOfPage"])
def test_schema_of_another_job_is_rejected(field: str) -> None:
    """原文声明的来源与输入详情链接冲突时，不把其他职位挂到当前平台 ID。"""
    payload = _job()
    payload[field] = "https://www.linkedin.com/jobs/view/9999999999/"
    with pytest.raises(ValidationFailedError, match="不一致"):
        extract_job(_html(payload), "HTML", identify_posting(_LINKEDIN))


def test_schema_mainentity_object_and_relative_url_are_supported() -> None:
    """主页面对象的显式 @id 可关联当前详情，跟踪信息不改变身份。"""
    payload = _job()
    payload["url"] = "/jobs/view/1234567890/?trk=test"
    payload["mainEntityOfPage"] = {"@type": "WebPage", "@id": _LINKEDIN}
    result = extract_job(_html(payload), "HTML", identify_posting(_LINKEDIN))
    assert result.title == "后端工程师"


def test_html_canonical_link_for_another_job_is_rejected() -> None:
    """缺少 JSON-LD 时仍校验页面显式 canonical，不接受另一页面的正文。"""
    html = '<link rel="canonical" href="https://www.linkedin.com/jobs/view/9999/"><main>负责后端服务。</main>'
    with pytest.raises(ValidationFailedError, match="不一致"):
        extract_job(html, "HTML", identify_posting(_LINKEDIN))


def test_multiple_explicit_locations_are_combined_without_remote_inference() -> None:
    """地址对象或文本都必须明确提供，不能推测远程工作安排。"""
    payload = _job()
    payload["jobLocation"] = [
        {"address": {"addressCountry": {"name": "中国"}, "addressLocality": "北京"}},
        {"address": "上海"},
    ]
    result = extract_job(_html(payload), "HTML", identify_posting(_LINKEDIN))
    assert result.location == "中国 北京 / 上海"


def test_oversized_body_fails_before_persisting_candidate() -> None:
    """输入和正文有确定上限，不能生成无法确认入库的候选。"""
    with pytest.raises(ValidationFailedError, match="过长"):
        extract_job("正文" * 50_001, "TEXT", identify_posting(_LINKEDIN))


def test_input_limit_counts_utf8_bytes() -> None:
    """1 MiB 边界按 UTF-8 字节计算，不能被中文字符绕过。"""
    with pytest.raises(ValidationFailedError, match="1 MiB"):
        extract_job("中" * 349_526, "HTML", identify_posting(_LINKEDIN))
