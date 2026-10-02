"""招聘详情页的本地适配：只识别链接并解析用户提供的内容，不访问网络。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal, cast
from urllib.parse import parse_qs, urljoin, urlsplit

from app.core.errors import ValidationFailedError
from app.core.responses import ErrorDetail
from app.modules.job.enums import JobSource

_EXTRACTOR_VERSION = "local-job-page-v1"
_MAX_INPUT_BYTES = 1_048_576
_MAX_JD_LENGTH = 100_000
_LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com", "cn.linkedin.com"}
_INDEED_HOSTS = {
    "indeed.com",
    "www.indeed.com",
    "cn.indeed.com",
    "uk.indeed.com",
    "ca.indeed.com",
    "au.indeed.com",
    "de.indeed.com",
    "fr.indeed.com",
}
_BOSS_HOSTS = {"zhipin.com", "www.zhipin.com"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "wbr"}
_EXCLUDED_TAGS = {
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "head",
    "template",
    "svg",
    "noscript",
    "form",
    "button",
    "select",
    "textarea",
    "iframe",
    "object",
}
_BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "ul", "ol", "h1", "h2", "h3", "h4", "table", "tr"}


@dataclass(frozen=True)
class PostingIdentity:
    """已校验的来源标识；平台 ID 与规范链接不能由人工确认表单改写。"""

    source: JobSource
    external_id: str
    canonical_url: str


@dataclass(frozen=True)
class ExtractedJob:
    """待人工核对的提取结果；空公司或标题表示未获取可靠事实。"""

    company_name: str
    title: str
    location: str | None
    raw_jd: str
    warnings: list[str]
    extractor_version: str


def _invalid(field: str, reason: str) -> ValidationFailedError:
    """构造字段错误，避免向 API 返回原始页面或内部解析异常。"""
    return ValidationFailedError(reason, details=[ErrorDetail(field=field, reason=reason)])


def identify_posting(url: str) -> PostingIdentity:
    """校验四站 HTTPS 详情链接并返回稳定身份，不访问链接。

    参数:
        url: 用户提供的职位详情链接；跟踪参数和片段会被移除。
    返回:
        平台、稳定职位 ID 与规范链接。
    异常:
        ValidationFailedError: 来源、协议、凭据、端口或详情页形态不受支持。
    """
    cleaned = url.strip()
    if not cleaned or len(cleaned) > 2048 or any(char.isspace() or ord(char) < 32 for char in cleaned):
        raise _invalid("url", "请提供有效的单个职位详情链接。")
    try:
        parsed = urlsplit(cleaned)
        port = parsed.port
    except ValueError as exc:
        raise _invalid("url", "职位链接格式不正确。") from exc
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise _invalid("url", "仅支持不含登录凭据和异常端口的 HTTPS 职位详情链接。")
    host = (parsed.hostname or "").lower()
    path = parsed.path
    if host in _LINKEDIN_HOSTS:
        match = re.fullmatch(r"/jobs/view/(?:[A-Za-z0-9_-]+-)?([1-9][0-9]{0,19})/?", path)
        if match:
            identifier = match[1]
            return PostingIdentity(JobSource.LINKEDIN, identifier, f"https://www.linkedin.com/jobs/view/{identifier}/")
    elif host in _INDEED_HOSTS:
        identifiers = parse_qs(parsed.query, keep_blank_values=True).get("jk", [])
        if (
            path.rstrip("/") == "/viewjob"
            and len(identifiers) == 1
            and re.fullmatch(r"[A-Fa-f0-9]{16}", identifiers[0])
        ):
            identifier = identifiers[0].lower()
            canonical_host = "www.indeed.com" if host == "indeed.com" else host
            return PostingIdentity(JobSource.INDEED, identifier, f"https://{canonical_host}/viewjob?jk={identifier}")
    elif host in _BOSS_HOSTS:
        match = re.fullmatch(r"/job_detail/([A-Za-z0-9_~\-]{8,128})\.html", path)
        if match:
            identifier = match[1]
            return PostingIdentity(JobSource.BOSS, identifier, f"https://www.zhipin.com/job_detail/{identifier}.html")
    elif host == "jobs.51job.com":
        match = re.fullmatch(r"/[A-Za-z0-9_-]+/([1-9][0-9]{0,19})\.html", path)
        if match:
            identifier = match[1]
            return PostingIdentity(JobSource.FIFTYONEJOB, identifier, f"https://jobs.51job.com{path}")
    raise _invalid("url", "目前仅支持领英、Indeed、BOSS 直聘和 51job 的受支持职位详情链接。")


class _PageParser(HTMLParser):
    """提取 JSON-LD 和可见正文；忽略脚本、样式、导航、表单及隐藏节点。"""

    def __init__(self) -> None:
        """初始化单页解析状态，不保存页面属性或完整 HTML。"""
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.json_scripts: list[str] = []
        self.canonical_urls: list[str] = []
        self._frames: list[tuple[str, bool]] = []
        self._skip_depth = 0
        self._json_script: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """记录结构边界；JSON-LD 只收集文本，不执行任何脚本。"""
        attributes = dict(attrs)
        if tag == "script" and (attributes.get("type") or "").strip().lower() == "application/ld+json":
            self._json_script = []
        if tag == "link" and "canonical" in (attributes.get("rel") or "").lower().split():
            href = attributes.get("href")
            if href:
                self.canonical_urls.append(href)
        style = re.sub(r"\s+", "", (attributes.get("style") or "").lower())
        excluded = (
            tag in _EXCLUDED_TAGS
            or "hidden" in attributes
            or attributes.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        if self._skip_depth == 0 and (tag in _BLOCK_TAGS or tag == "br"):
            self.text_parts.append("\n")
        if tag not in _VOID_TAGS:
            self._frames.append((tag, excluded))
            self._skip_depth += int(excluded)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """兼容自闭合节点，避免隐藏状态泄漏到之后的正文。"""
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        """仅关闭确实存在的节点，畸形闭合标签不能解除正文过滤。"""
        if tag == "script" and self._json_script is not None:
            self.json_scripts.append("".join(self._json_script))
            self._json_script = None
        for index in range(len(self._frames) - 1, -1, -1):
            if self._frames[index][0] == tag:
                self._skip_depth -= sum(int(excluded) for _, excluded in self._frames[index:])
                del self._frames[index:]
                break
        if self._skip_depth == 0 and tag in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        """只保留正在读取的 JSON-LD 或未被屏蔽的文本。"""
        if self._json_script is not None:
            self._json_script.append(data)
        elif self._skip_depth == 0:
            self.text_parts.append(data)

    def visible_text(self) -> str:
        """压缩布局空白，保留正文段落，不使用网页 title 推断职位名。"""
        return "\n".join(line for part in "".join(self.text_parts).splitlines() if (line := " ".join(part.split())))

    def ensure_complete(self) -> None:
        """拒绝未闭合的结构脚本，不能把损坏的 JSON-LD 当作无结构内容。"""
        if self._json_script is not None:
            raise _invalid("content", "页面 JSON-LD 未完整闭合，请改为粘贴职位正文。")


def _parse_html(content: str) -> _PageParser:
    """解析不可信 HTML，未闭合脚本或深层异常不形成候选事实。"""
    parser = _PageParser()
    try:
        parser.feed(content)
        parser.close()
    except (ValueError, RecursionError) as exc:
        raise _invalid("content", "页面内容无法安全解析，请改为粘贴职位正文。") from exc
    parser.ensure_complete()
    return parser


def _json_mapping(value: object, field: str) -> dict[str, object]:
    """只接受 JSON 对象，不把数组、数字等错误形态转成职位字段。"""
    if not isinstance(value, dict):
        raise _invalid("content", f"页面结构中的 {field} 不是有效对象，请改为粘贴职位正文。")
    return cast(dict[str, object], value)


def _reject_json_constant(value: str) -> None:
    """拒绝 JSON 标准以外的 NaN/Infinity，避免非确定结构混入候选。"""
    raise _invalid("content", "页面结构包含非标准 JSON 值，请改为粘贴职位正文。")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """拒绝重复 JSON 字段，避免不同解析器采用不同的职位来源或描述。"""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid("content", "页面结构存在重复字段，请改为粘贴职位正文。")
        result[key] = value
    return result


def _job_postings(scripts: list[str]) -> list[dict[str, object]]:
    """查找数组或图中的职位对象；设置节点上限以免异常结构耗尽递归资源。"""
    jobs: list[dict[str, object]] = []
    for script in scripts:
        try:
            payload: object = json.loads(
                script,
                parse_constant=_reject_json_constant,
                object_pairs_hook=_unique_json_object,
            )
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise _invalid("content", "页面 JSON-LD 已损坏，请改为粘贴职位正文。") from exc
        if not isinstance(payload, (dict, list)):
            raise _invalid("content", "页面 JSON-LD 必须是对象或数组，请改为粘贴职位正文。")
        pending: list[object] = [payload]
        visited = 0
        while pending:
            value = pending.pop()
            visited += 1
            if visited > 10_000:
                raise _invalid("content", "页面结构过于复杂，请仅粘贴单个职位正文。")
            if isinstance(value, list):
                pending.extend(cast(list[object], value))
            elif isinstance(value, dict):
                node = cast(dict[str, object], value)
                type_value = node.get("@type")
                types = cast(list[object], type_value) if isinstance(type_value, list) else [type_value]
                if "JobPosting" in types or "https://schema.org/JobPosting" in types:
                    jobs.append(node)
                if "@graph" in node and not isinstance(node["@graph"], (dict, list)):
                    raise _invalid("content", "页面 JSON-LD 图结构不正确，请改为粘贴职位正文。")
                pending.extend(node.values())
    if len(jobs) > 1:
        raise _invalid("content", "页面包含多个职位，无法确定当前职位；请只提供单个职位详情正文。")
    return jobs


def _optional_text(value: object, field: str, limit: int = 200) -> str:
    """接受缺失字段，拒绝错误类型及超长字段，不通过字符串化猜测事实。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid("content", f"页面结构中的 {field} 不是有效文本，请改为粘贴职位正文。")
    text = value.strip()
    if len(text) > limit:
        raise _invalid("content", f"页面结构中的 {field} 过长，请改为粘贴职位正文。")
    return text


def _location(value: object) -> str | None:
    """读取显式地址字段；多个地点只组合已提供地址，不推断远程工作。"""
    if value is None:
        return None
    places = cast(list[object], value) if isinstance(value, list) else [value]
    locations: list[str] = []
    for item in places:
        place = _json_mapping(item, "jobLocation")
        address = place.get("address")
        if address is None:
            continue
        if isinstance(address, str):
            text = _optional_text(address, "jobLocation.address")
        else:
            fields = _json_mapping(address, "jobLocation.address")
            parts: list[str] = []
            for key in ("addressCountry", "addressRegion", "addressLocality", "streetAddress"):
                entry = fields.get(key)
                if key == "addressCountry" and isinstance(entry, dict):
                    entry = _json_mapping(cast(object, entry), "addressCountry").get("name")
                if part := _optional_text(entry, f"jobLocation.address.{key}"):
                    parts.append(part)
            text = " ".join(parts)
        if text and text not in locations:
            locations.append(text)
    return _optional_text(" / ".join(locations), "jobLocation") or None


def _verify_page_url(url: str, identity: PostingIdentity) -> None:
    """校验页面显式来源与输入身份一致，避免把另一职位的结构写入该平台 ID。"""
    try:
        linked = identify_posting(urljoin(identity.canonical_url, url))
    except ValidationFailedError as exc:
        raise _invalid("content", "页面中的职位链接无效，请重新提供对应职位的内容。") from exc
    if linked.source != identity.source or linked.external_id != identity.external_id:
        raise _invalid("content", "页面中的职位链接与输入链接不一致，请重新提供对应职位的内容。")


def _validate_description(text: str) -> str:
    """拒绝空正文、明确登录/验证占位页及超长描述，错误不包含原文。"""
    raw_jd = text.strip()
    if not raw_jd:
        raise _invalid("content", "未找到职位正文，请粘贴职位描述后重试。")
    if len(raw_jd) > _MAX_JD_LENGTH:
        raise _invalid("content", "职位正文过长，请只保留当前职位的描述。")
    lowered = raw_jd.lower()
    gate_phrases = (
        "请登录",
        "登录后查看",
        "登录后继续",
        "请先登录",
        "请完成验证",
        "请输入验证码",
        "安全验证",
        "verify you are human",
        "sign in to continue",
        "sign in to view",
        "log in to view",
        "access denied",
    )
    if len(raw_jd) < 300 and (
        any(phrase in lowered for phrase in gate_phrases)
        or lowered in {"登录", "注册", "验证码", "captcha", "sign in", "log in", "robot check"}
    ):
        raise _invalid("content", "提供的内容是登录或验证提示，未包含可导入的职位正文。")
    return raw_jd


def extract_job(content: str, mode: Literal["HTML", "TEXT"], identity: PostingIdentity) -> ExtractedJob:
    """解析本地内容形成候选，不执行脚本、不推断职位事实、不访问外部服务。

    参数:
        content: 用户主动提供的 HTML 或单个职位的可见正文。
        mode: HTML 读取单个 JSON-LD 职位；TEXT 保留正文供人工填写事实。
        identity: 已通过 identify_posting 校验的详情页身份。
    返回:
        必要字段、纯文本 JD、缺失提示和固定提取器版本。
    异常:
        ValidationFailedError: 空页、多个职位、损坏结构、类型错误或页面身份不匹配。
    """
    try:
        input_size = len(content.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise _invalid("content", "页面内容存在无效字符，请重新复制职位正文。") from exc
    if not content.strip() or input_size > _MAX_INPUT_BYTES:
        raise _invalid("content", "请提供不超过 1 MiB 的单个职位页面内容。")
    if mode not in ("HTML", "TEXT"):
        raise _invalid("mode", "内容格式仅支持 HTML 或 TEXT。")
    warnings: list[str] = []
    company_name = title = ""
    location: str | None = None
    if mode == "TEXT":
        raw_jd = _validate_description(content)
        warnings.append("已保留用户提供的正文；公司、职位标题和地点需人工核对填写。")
    else:
        parser = _parse_html(content)
        for url in parser.canonical_urls:
            _verify_page_url(url, identity)
        jobs = _job_postings(parser.json_scripts)
        if not jobs:
            raw_jd = _validate_description(parser.visible_text())
            warnings.append("未找到可靠的职位结构；已保留页面正文，请只保留当前职位内容并填写公司和标题。")
        else:
            job = jobs[0]
            for key in ("url", "mainEntityOfPage"):
                url_value = job.get(key)
                if url_value is not None:
                    if isinstance(url_value, dict):
                        url_value = _json_mapping(cast(object, url_value), key).get("@id")
                    url = _optional_text(url_value, key, 2048)
                    if url:
                        _verify_page_url(url, identity)
            title = _optional_text(job.get("title"), "title")
            organization = job.get("hiringOrganization")
            if organization is not None:
                company_name = _optional_text(_json_mapping(organization, "hiringOrganization").get("name"), "公司名称")
            location = _location(job.get("jobLocation"))
            description = _optional_text(job.get("description"), "description", _MAX_INPUT_BYTES)
            raw_jd = _validate_description(_parse_html(description).visible_text())
            warnings.append("职位字段来自用户提供的页面结构，仍需人工核对。")
    if not company_name:
        warnings.append("未获取公司名称，请人工填写。")
    if not title:
        warnings.append("未获取职位标题，请人工填写。")
    return ExtractedJob(company_name, title, location, raw_jd, warnings, _EXTRACTOR_VERSION)
