"""简历文档导入：只把可回溯的 AI 候选经人工确认后写入 Profile。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import date
from html.parser import HTMLParser
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai_service
from app.ai.llm import gateway
from app.core.config import AppEnv, get_settings
from app.core.errors import ConflictError, ValidationFailedError
from app.core.responses import ErrorDetail

from . import repository as repo
from .enums import ClaimStatus, EvidenceSourceType, VerificationStatus
from .import_fixture import FIXTURE_SOURCE_HASH, FIXTURE_TEXT, mock_extract_profile
from .models import (
    PersonalProfile,
    ProfileEducation,
    ProfileEvidence,
    ProfileExperience,
    ProfileProject,
    ProfileSkill,
)
from .schemas import ProfileLink
from .service import normalize_skill_name

MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_PDF_PAGES = 10
MAX_TEXT_CHARS = 40_000
# 预览不会写入业务事实；只对大模型服务明确标记为短暂的失败额外尝试一次，避免无界重发简历文本。
MAX_PREVIEW_AI_ATTEMPTS = 2
PREVIEW_RETRY_DELAY_SECONDS = 1.0
logger = logging.getLogger(__name__)
# 临时强制 mock 的开关：保持 None 表示走真实大模型服务（2026-09-27 已从 local 强制 mock 改回）。
# 需要离线联调、不配置服务商与凭据时，可临时把它设成 AppEnv.LOCAL，或用下面的
# JOBARK_PROFILE_IMPORT_FIXTURE 在 local/test 开启内置夹具。
_FORCE_MOCK_EXTRACTION_IN: AppEnv | None = None


def _mock_extraction_enabled() -> bool:
    """是否用内置固定值替代大模型抽取。

    返回:
        bool: 需要 mock 时返回 True。

    注意:
        两组条件都天然排除生产：临时开关只在指定的运行环境生效，而 `profile_import_fixture`
        在 prod 会被配置校验直接拒绝开启，因此样例数据不可能进入真实档案。
        mock 只替换"外部输入"，候选仍走同一套 Schema 与逐字原文校验。
    """
    settings = get_settings()
    if _FORCE_MOCK_EXTRACTION_IN is not None and settings.app_env is _FORCE_MOCK_EXTRACTION_IN:
        return True
    return settings.profile_import_fixture


class ResumeUpload(BaseModel):
    """上传文档的 JSON 传输体；限制 base64 长度避免大文件占用过多内存。"""

    filename: str = Field(min_length=1, max_length=200, description="原始文件名，仅用于判断格式和显示来源。")
    content_base64: str = Field(min_length=1, max_length=4_200_000, description="PDF/HTML 文件的 base64 内容。")


# 候选条目的来源语义（见 docs/requirements/v1.md 2.1）。
# 两类来源必须能被区分：否则"用户新增条目"要么进不来（强制摘录），要么只能靠假摘录混进来。
ItemOrigin = Literal["RESUME", "MANUAL"]


class SourcedItemBase(BaseModel):
    """带来源语义的候选条目基类。

    - `RESUME`：内容来自简历原文，必须带真实摘录。预览阶段逐字校验摘录确实存在于上传文件，
      字段取值也必须落在摘录内；摘录是来源凭证，不是可填可不填的备注。
    - `MANUAL`：用户本人填写，或把 AI 条目改到摘录之外。**不接受摘录**——允许携带就等于允许
      用一段复制来的原文给编造内容做背书。

    来源只决定"挂哪条证据"和"要不要做原文校验"，两类条目都要通过各自的必填、长度与日期顺序校验。
    """

    model_config = ConfigDict(extra="forbid")
    origin: ItemOrigin = Field(description="RESUME=来自简历原文摘录；MANUAL=本人填写。")
    source_quote: str | None = Field(
        default=None,
        max_length=500,
        description="原文摘录；仅 RESUME 条目提供，MANUAL 条目携带会被拒绝。",
    )

    @model_validator(mode="after")
    def _validate_origin_quote(self) -> Self:
        """校验来源与摘录的搭配。

        返回:
            Self: 校验通过的自身实例。

        异常:
            ValueError: RESUME 缺少摘录，或 MANUAL 携带摘录时抛出（FastAPI 转为 422）。
        """
        quote = (self.source_quote or "").strip()
        if self.origin == "RESUME" and quote == "":
            raise ValueError("origin 为 RESUME 的条目必须提供 source_quote。")
        if self.origin == "MANUAL" and quote != "":
            raise ValueError(
                "origin 为 MANUAL 的条目不接受 source_quote：请勿用摘录给本人填写的内容做来源背书。"
            )
        return self


class SourcedSkill(SourcedItemBase):
    """技能候选，不代表已验证能力。"""

    name: str = Field(min_length=1, max_length=100)


class SourcedExperience(SourcedItemBase):
    """工作经历候选。"""

    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date | None = None
    location: str | None = Field(default=None, max_length=100)
    responsibilities: str | None = Field(default=None, max_length=3000)
    achievements: str | None = Field(default=None, max_length=3000)


class SourcedProject(SourcedItemBase):
    """项目经历候选。

    日期允许留空，因为简历里的项目常常只给名称与技术栈。

    注意:
        除 `description`（项目说明）外，这里还接受 `responsibilities` 与 `achievements`：
        模型提取项目时习惯沿用工作经历的字段命名，而简历里的项目也确实常把职责与成果分开写。
        这三个字段在写入时按段落合并进 `ProfileProject.description`（见 `_project_description`），
        Profile 的项目事实没有单独的职责/成果列；合并只做拼接，不产生原文之外的内容。
    """

    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=3000)
    responsibilities: str | None = Field(default=None, max_length=3000)
    achievements: str | None = Field(default=None, max_length=3000)
    tech_stack: list[str] = Field(default_factory=list[str], max_length=20)
    url: str | None = Field(default=None, max_length=2048)
    start_date: date | None = None
    end_date: date | None = None


class SourcedEducation(SourcedItemBase):
    """教育经历候选。"""

    school: str = Field(min_length=1, max_length=200)
    major: str | None = Field(default=None, max_length=200)
    degree: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    end_date: date | None = None


class ImportCandidate(BaseModel):
    """未确认的档案候选；覆盖可从简历提取的基本信息与四类事实（技能、工作经历、项目、教育）。

    字段与"创建个人档案"表单（前端 `basicsFields.ts`）逐项对齐：两个页面共用同一个表单，
    因此候选也必须能承载个人简介与公开链接，否则两边又会各显示一套字段。
    `summary` 与 `links` 都有默认值，旧客户端不传它们仍然可用（向后兼容）。
    """

    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1, max_length=100)
    name_quote: str = Field(min_length=1, max_length=500)
    headline: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=3000)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=100)
    links: list[ProfileLink] = Field(default_factory=list[ProfileLink], max_length=20)
    skills: list[SourcedSkill] = Field(default_factory=list[SourcedSkill], max_length=40)
    experiences: list[SourcedExperience] = Field(default_factory=list[SourcedExperience], max_length=20)
    projects: list[SourcedProject] = Field(default_factory=list[SourcedProject], max_length=20)
    educations: list[SourcedEducation] = Field(default_factory=list[SourcedEducation], max_length=20)


class ImportPreviewCompleteness(BaseModel):
    """预览覆盖情况，防止界面把局部候选误呈现为完整抽取结果。"""

    status: Literal["COMPLETE", "PARTIAL"]
    valid_item_count: int = Field(ge=0)
    rejected_item_count: int = Field(ge=0)
    unmapped_field_count: int = Field(ge=0)
    excluded_field_count: int = Field(ge=0)


class ImportPreviewRejectedItem(BaseModel):
    """未进入候选列表的模型条目；不包含原文或模型取值，避免日志/API 扩散简历内容。"""

    group: str
    index: int = Field(ge=0)
    code: Literal["SCHEMA_INVALID", "EVIDENCE_INVALID"]
    fields: list[str] = Field(default_factory=list)
    message: str


class ImportPreviewWarning(BaseModel):
    """未进入候选事实的字段诊断；只保留字段名，不把未经证实的内容伪装成事实。"""

    group: str
    index: int = Field(ge=0)
    code: Literal["UNMAPPED_MODEL_FIELD", "FIELD_NOT_IN_QUOTE", "FIELD_ALIAS_MAPPED"]
    fields: list[str] = Field(min_length=1)
    message: str


class ImportPreviewRead(BaseModel):
    """供用户核对、选择的候选；原文文件不会保存在服务端。"""

    filename: str
    source_hash: str
    candidate: ImportCandidate
    completeness: ImportPreviewCompleteness
    rejected_items: list[ImportPreviewRejectedItem] = Field(default_factory=list[ImportPreviewRejectedItem])
    warnings: list[ImportPreviewWarning] = Field(default_factory=list[ImportPreviewWarning])
    fixture: bool = Field(
        default=False,
        description="为 true 表示本次候选来自内置开发夹具，不是真实大模型抽取结果。",
    )


class _ImportCandidateRoot(BaseModel):
    """模型输出的根信封校验器；集合项另行隔离校验，根协议错误仍整体失败。"""

    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1, max_length=100)
    name_quote: str = Field(min_length=1, max_length=500)
    headline: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=3000)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=100)
    # 与其它集合一样只做"是列表"这一层校验，条目格式在候选解析里逐项隔离。
    links: list[Any] = Field(default_factory=list)
    skills: list[Any] = Field(default_factory=list)
    experiences: list[Any] = Field(default_factory=list)
    projects: list[Any] = Field(default_factory=list)
    educations: list[Any] = Field(default_factory=list)


class ImportConfirmRequest(ResumeUpload):
    """确认写入时重传原文件，防止客户端把未经验证的候选单独提交。"""

    source_hash: str = Field(min_length=64, max_length=64)
    candidate: ImportCandidate
    skill_indices: list[int] = Field(default_factory=list[int], max_length=40)
    experience_indices: list[int] = Field(default_factory=list[int], max_length=20)
    project_indices: list[int] = Field(default_factory=list[int], max_length=20)
    education_indices: list[int] = Field(default_factory=list[int], max_length=20)
    confirmed: bool = Field(description="用户已逐项核对并确认写入。")


class ImportApplyRead(BaseModel):
    """确认导入的结果；已有档案不会被覆盖。"""

    profile_id: str
    created_profile: bool
    skills_added: int
    experiences_added: int
    projects_added: int
    educations_added: int
    manual_item_count: int = Field(
        default=0,
        description="本次写入的条目中按「本人填写」记录来源的条数（用户新增或改到摘录之外）。",
    )


@dataclass(frozen=True)
class ParsedDocument:
    """仅在本次请求中使用的本地提取结果。"""

    filename: str
    text: str
    source_hash: str


class _ResumeHTMLParser(HTMLParser):
    """只读取 HTML 可见文本，不执行脚本或抓取远程资源。"""

    def __init__(self) -> None:
        """初始化文本缓冲区与忽略标签计数。"""
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """忽略非正文内容并给块级元素增加分隔。"""
        if tag in {"script", "style", "noscript", "svg", "head"}:
            self.suppressed += 1
        elif tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"} and not self.suppressed:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """结束忽略区域。"""
        if tag in {"script", "style", "noscript", "svg", "head"} and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data: str) -> None:
        """收集可见文本。"""
        if not self.suppressed:
            self.parts.append(data)


def _normalize(text: str) -> str:
    """折叠排版空白，供原文摘录匹配与模型输入使用。"""
    return re.sub(r"\s+", " ", text).strip()


def parse_document(upload: ResumeUpload) -> ParsedDocument:
    """本地解析受限 PDF/HTML；不保存原文件，不访问外部地址。"""
    filename = PurePosixPath(upload.filename.replace("\\", "/")).name
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in {".pdf", ".html", ".htm"}:
        raise ValidationFailedError("仅支持 PDF 或 HTML 简历文件。")
    try:
        raw = base64.b64decode(upload.content_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValidationFailedError("上传文件编码无效。") from error
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValidationFailedError("文件必须非空且不超过 3 MB。")
    if suffix == ".pdf":
        if not raw.startswith(b"%PDF-"):
            raise ValidationFailedError("文件不是有效的 PDF。")
        try:
            reader = PdfReader(BytesIO(raw), strict=False)
            if reader.is_encrypted or len(reader.pages) > MAX_PDF_PAGES:
                raise ValidationFailedError("PDF 不得加密且最多 10 页。")
            content = "\n".join(page.extract_text() or "" for page in reader.pages)
        except ValidationFailedError:
            raise
        except Exception as error:
            raise ValidationFailedError("PDF 无法读取，请检查文件是否损坏。") from error
    else:
        try:
            html = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                html = raw.decode("gb18030")
            except UnicodeDecodeError as error:
                raise ValidationFailedError("HTML 编码不受支持，请使用 UTF-8。") from error
        parser = _ResumeHTMLParser()
        parser.feed(html)
        content = " ".join(parser.parts)
    text = _normalize(content)
    if not text:
        raise ValidationFailedError("未提取到文字；扫描版 PDF 暂不支持 OCR，请上传带文字层的简历。")
    if len(text) > MAX_TEXT_CHARS:
        raise ValidationFailedError("简历文字过长，请缩短至 4 万字符以内。")
    return ParsedDocument(filename=filename, text=text, source_hash=hashlib.sha256(raw).hexdigest())


def _log_candidate_invalid(group: str, index: int | None, reason: str, **extra: object) -> None:
    """记录候选校验失败的结构化原因，不带原文或候选取值。"""
    logger.warning(
        "候选内容未通过原文校验",
        extra={
            "event": "profile_import_candidate_invalid",
            "reason": reason,
            "candidate_group": group,
            "candidate_index": index,
            **extra,
        },
    )


def _item_field_values(
    item: SourcedSkill | SourcedExperience | SourcedProject | SourcedEducation,
) -> list[tuple[str, str | None]]:
    """返回必须被对应摘录覆盖的 (字段名, 取值)；字段列表与候选模型显式对齐。

    带字段名是因为错误要按字段返回：只说"这条不合法"，用户不知道自己改的是哪个输入框。
    """
    if isinstance(item, SourcedSkill):
        return [("name", item.name)]
    if isinstance(item, SourcedExperience):
        return [
            ("company", item.company),
            ("title", item.title),
            ("location", item.location),
            ("responsibilities", item.responsibilities),
            ("achievements", item.achievements),
        ]
    if isinstance(item, SourcedProject):
        return [
            ("name", item.name),
            ("role", item.role),
            ("description", item.description),
            ("responsibilities", item.responsibilities),
            ("achievements", item.achievements),
            ("url", item.url),
            *[(f"tech_stack.{position}", value) for position, value in enumerate(item.tech_stack)],
        ]
    return [("school", item.school), ("major", item.major), ("degree", item.degree)]


def _check_sourced_item(
    group: str,
    index: int,
    item: SourcedSkill | SourcedExperience | SourcedProject | SourcedEducation,
    text: str,
    *,
    allow_deviation: bool,
) -> bool:
    """校验条目的结构与原文证据，返回它是否应按「本人填写」记录来源。

    参数:
        group: 条目分组名（单数），用于日志与错误字段路径。
        index: 条目在分组内的下标，用于日志与错误字段路径。
        item: 待校验条目。
        text: 本地提取的简历原文。
        allow_deviation: 是否允许 RESUME 条目偏离摘录（确认阶段为 True）。开启后偏离不报错，
            而是转为「本人填写」——内容变了就不该继续借旧摘录做证明。

    返回:
        bool: True 表示该条目应按「本人填写」记录来源（`MANUAL` 条目恒为 True）。

    异常:
        ValidationFailedError: 日期倒序、摘录无法定位到原文，或（未开启偏离容忍时）取值超出摘录。

    注意:
        `MANUAL` 条目不做任何原文校验：用户新增的条目本来就没有摘录，要求它提供摘录只会逼用户
        编造一段原文。它们的可信度由「本人填写」这一来源如实表达，而不是靠摘录。
    """
    start_date = getattr(item, "start_date", None)
    end_date = getattr(item, "end_date", None)
    if start_date is not None and end_date is not None and end_date < start_date:
        _log_candidate_invalid(group, index, "end_date_before_start_date")
        raise ValidationFailedError(
            "候选的结束日期早于开始日期，未写入个人档案。",
            details=[
                ErrorDetail(
                    field=f"candidate.{group}s.{index}.end_date",
                    reason="结束日期不得早于开始日期。",
                )
            ],
        )
    if item.origin == "MANUAL":
        return True
    quote = item.source_quote or ""
    normalized_quote = _normalize(quote)
    if normalized_quote not in text:
        _log_candidate_invalid(group, index, "quote_not_in_document")
        raise ValidationFailedError(
            "候选内容无法逐字定位到简历原文，未写入个人档案。",
            details=[
                ErrorDetail(
                    field=f"candidate.{group}s.{index}.source_quote",
                    reason="摘录无法在上传的简历原文中逐字定位；若内容是你自己填写的，请按本人填写提交。",
                )
            ],
        )
    deviating = [
        name for name, value in _item_field_values(item) if value and _normalize(value) not in normalized_quote
    ]
    if not deviating:
        for item_date in (start_date, end_date):
            if item_date and str(item_date.year) not in quote:
                deviating.append("start_date" if item_date is start_date else "end_date")
    if deviating and not allow_deviation:
        _log_candidate_invalid(group, index, "value_not_in_quote", fields=deviating)
        raise ValidationFailedError(
            "候选内容无法逐字定位到简历原文，未写入个人档案。",
            details=[
                ErrorDetail(
                    field=f"candidate.{group}s.{index}.{name}",
                    reason="取值未出现在原文摘录中。",
                )
                for name in deviating
            ],
        )
    return bool(deviating)


def _filter_unquoted_project_fields(item: SourcedProject, text: str, index: int) -> tuple[SourcedProject, list[str]]:
    """保留项目的可证实骨架，剔除不在同一原文摘录内的可选字段。

    项目名称和摘录仍是不可放宽的锚点：两者任一无效时整条项目拒绝。其余字段若是模型摘要、
    改写或摘录遗漏，则不作为简历事实进入候选；用户可在预览中补回，确认时会转为本人陈述。
    """
    quote = item.source_quote or ""
    normalized_quote = _normalize(quote)
    if normalized_quote not in text:
        _log_candidate_invalid("project", index, "quote_not_in_document")
        raise ValidationFailedError("候选内容无法逐字定位到简历原文，未写入个人档案。")
    if _normalize(item.name) not in normalized_quote:
        _log_candidate_invalid("project", index, "value_not_in_quote", candidate_field="name")
        raise ValidationFailedError("候选项目名称无法逐字定位到简历原文，未进入待确认列表。")

    update: dict[str, object] = {}
    excluded: list[str] = []
    for field in ("role", "description", "responsibilities", "achievements", "url"):
        value = getattr(item, field)
        if value and _normalize(value) not in normalized_quote:
            update[field] = None
            excluded.append(field)
    verified_tech_stack = [value for value in item.tech_stack if _normalize(value) in normalized_quote]
    if len(verified_tech_stack) != len(item.tech_stack):
        update["tech_stack"] = verified_tech_stack
        excluded.append("tech_stack")
    for field in ("start_date", "end_date"):
        value = getattr(item, field)
        if value and str(value.year) not in quote:
            update[field] = None
            excluded.append(field)

    sanitized = item.model_copy(update=update)
    if sanitized.start_date and sanitized.end_date and sanitized.end_date < sanitized.start_date:
        # 日期次序异常时没有可信方式推断哪一个错误；保留项目但不让错误日期成为候选事实。
        sanitized = sanitized.model_copy(update={"start_date": None, "end_date": None})
        excluded.extend(field for field in ("start_date", "end_date") if field not in excluded)
    return sanitized, excluded


# 模型常沿用工作经历的字段命名描述项目；这些等价键只在 `name` 缺失时用于补齐名称锚点。
_PROJECT_NAME_ALIASES = ("title", "project_name")
# 技术栈被模型写成一句话时按常见分隔符拆分；拆分只改变形态，不产生原文之外的取值。
_TECH_STACK_SEPARATORS = re.compile(r"[,，、;；|/]+")


def _normalize_project_item(raw_mapping: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """把模型沿用其它分组命名的项目字段归一到候选契约。

    参数:
        raw_mapping: 模型返回的项目对象原始字段。

    返回:
        tuple[dict[str, Any], list[str]]: 归一化后的字段字典，以及实际发生归一化的字段名。

    注意:
        只做两类形态归一：等价字段名（如 `title`）补到 `name`、字符串技术栈拆成列表。
        取值本身一字不改，因此归一化后仍必须通过与其它字段完全相同的原文摘录逐字校验。
        项目名称是不可放宽的锚点，所以仅在 `name` 缺失或为空时才接受等价字段——`title`
        也可能是角色，不能在已有 `name` 时覆盖它。
    """
    normalized = dict(raw_mapping)
    mapped: list[str] = []
    name = normalized.get("name")
    if not (isinstance(name, str) and name.strip()):
        for alias in _PROJECT_NAME_ALIASES:
            candidate = normalized.get(alias)
            if isinstance(candidate, str) and candidate.strip():
                normalized["name"] = candidate
                del normalized[alias]
                mapped.append(alias)
                break
    tech_stack = normalized.get("tech_stack")
    if isinstance(tech_stack, str):
        parts = [part.strip() for part in _TECH_STACK_SEPARATORS.split(tech_stack) if part.strip()]
        if parts:
            normalized["tech_stack"] = parts
            mapped.append("tech_stack")
    return normalized, mapped


def _link_in_text(link: ProfileLink, text: str) -> bool:
    """公开链接是否能在简历原文中逐字定位。

    简历里的地址常写作 `github.com/foo`，而模型会补成 `https://github.com/foo`，因此地址按
    “去掉协议与尾斜杠”后比较；名称（如 GitHub、个人博客）同样必须来自原文，否则等于替用户
    编造一个称呼。任一半定位不到就不采用，避免把编造的链接写进档案。
    """
    normalized_url = _normalize(link.url).rstrip("/")
    forms = {normalized_url}
    for prefix in ("https://", "http://"):
        if normalized_url.startswith(prefix):
            forms.add(normalized_url[len(prefix) :].rstrip("/"))
    if not any(form and form in text for form in forms):
        return False
    return _normalize(link.label) in text


def _parse_links(raw_links: list[Any]) -> tuple[list[ProfileLink], int]:
    """把模型给出的公开链接逐项校验为 `ProfileLink`，返回可用条目与被丢弃的条数。

    条目级隔离：单条链接格式不对只丢弃该条，不影响其它基本信息与四类事实。
    """
    kept: list[ProfileLink] = []
    dropped = 0
    for raw_link in raw_links:
        if not isinstance(raw_link, dict):
            dropped += 1
            continue
        try:
            kept.append(ProfileLink.model_validate(raw_link))
        except ValidationError:
            dropped += 1
    return kept, dropped


def _filter_unquoted_basics(candidate: ImportCandidate, text: str) -> tuple[ImportCandidate, list[str]]:
    """清空无法逐字定位的可选基本信息（个人简介、公开链接），返回清洗后的候选与被清空的字段。

    基本信息整体是可信锚点，但个人简介与公开链接是**可缺省的长文本/列表**：模型很容易用自己的
    话复述一段自我评价，若因此整体拒绝，用户会连同可验证的技能与经历一起丢掉——项目经历曾经
    踩过同样的坑。因此这两个字段按字段级隔离：定位不到就留空并提示，绝不伪装成简历事实。

    注意:
        只在预览阶段调用。确认阶段允许用户改到摘录之外（那是本人陈述），因此不清洗。
    """
    updates: dict[str, Any] = {}
    excluded: list[str] = []
    if candidate.summary and _normalize(candidate.summary) not in text:
        updates["summary"] = None
        excluded.append("summary")
    evidenced_links = [link for link in candidate.links if _link_in_text(link, text)]
    if len(evidenced_links) != len(candidate.links):
        updates["links"] = evidenced_links
        excluded.append("links")
    if not updates:
        return candidate, []
    return candidate.model_copy(update=updates), excluded


def _check_basics(candidate: ImportCandidate, text: str, *, allow_edits: bool) -> None:
    """校验姓名及可选基本信息；姓名与姓名摘录是整个候选信封的最小可信锚点。"""
    normalized_name_quote = _normalize(candidate.name_quote)
    if normalized_name_quote not in text or _normalize(candidate.full_name) not in normalized_name_quote:
        _log_candidate_invalid("basics", None, "name_not_in_quote")
        raise ValidationFailedError("候选基本信息无法逐字定位到简历原文，未写入个人档案。")
    for field in ("headline", "email", "phone", "city"):
        value = getattr(candidate, field)
        if value and _normalize(value) not in text:
            if not allow_edits:
                _log_candidate_invalid("basics", None, "basic_field_not_in_document", candidate_field=field)
                raise ValidationFailedError("候选基本信息无法逐字定位到简历原文，未写入个人档案。")
            logger.info(
                "候选基本信息经用户修订",
                extra={"event": "profile_import_candidate_edited", "candidate_field": field},
            )


def _check_candidate(candidate: ImportCandidate, text: str) -> set[tuple[str, int]]:
    """校验确认阶段的候选，返回应按「本人填写」记录来源的 (分组, 下标) 集合。

    参数:
        candidate: 待写入的候选，可能已被用户在候选页修改或新增。
        text: 本地提取的简历原文。

    返回:
        set[tuple[str, int]]: 需要挂「本人填写」证据的条目集合。

    异常:
        ValidationFailedError: 基本信息锚点失效、`RESUME` 条目摘录无法定位到原文、日期顺序非法，
            或 `MANUAL` 条目携带摘录（伪装简历来源）。

    注意:
        确认阶段与预览阶段的差别只在"偏离摘录"的处理：预览阶段仍逐字校验，模型改写原文的内容
        无法进入候选；确认阶段把偏离摘录的 `RESUME` 条目降级为「本人填写」，而不是拒绝——
        用户有权把 AI 的结果改成事实，但改写后的内容不能再借旧摘录做证明。
        `MANUAL` 条目（用户新增或已改写）不校验摘录，它们的来源如实记为本人填写。
    """
    _check_basics(candidate, text, allow_edits=True)
    manual: set[tuple[str, int]] = set()
    for group, items in (
        ("skill", candidate.skills),
        ("experience", candidate.experiences),
        ("project", candidate.projects),
        ("education", candidate.educations),
    ):
        for index, item in enumerate(items):
            if _check_sourced_item(group, index, item, text, allow_deviation=True):
                manual.add((group, index))
    return manual


def _ensure_no_duplicate_items(
    group: str,
    items: list[tuple[int, SourcedSkill | SourcedExperience | SourcedProject | SourcedEducation]],
) -> list[ErrorDetail]:
    """找出同一次提交里重复的条目，返回字段级错误。

    参数:
        group: 条目分组名（单数）。
        items: (原始下标, 条目) 列表，仅包含用户选中的条目。

    返回:
        list[ErrorDetail]: 重复项的错误明细；没有重复时为空列表。

    注意:
        只检查同一次提交内部的重复：与档案中已有条目的重复由写入阶段按既有去重规则跳过
        （已有档案导入只补充未重复条目）。用户新填的条目重复属于输入错误，应在写入前指出。
    """
    seen: dict[str, int] = {}
    details: list[ErrorDetail] = []
    for index, item in items:
        key = _item_identity(group, item)
        first = seen.get(key)
        if first is None:
            seen[key] = index
            continue
        details.append(
            ErrorDetail(
                field=f"candidate.{group}s.{index}",
                reason=f"与第 {first + 1} 条重复，请删除其中一条。",
            )
        )
    return details


def _item_identity(group: str, item: SourcedSkill | SourcedExperience | SourcedProject | SourcedEducation) -> str:
    """条目的业务唯一键，用于去重判断（大小写与空白归一）。

    参数:
        group: 条目分组名（单数）。
        item: 候选条目。

    返回:
        str: 归一化后的唯一键。
    """
    if isinstance(item, SourcedSkill):
        return normalize_skill_name(item.name)
    if isinstance(item, SourcedExperience):
        return "|".join([_normalize(item.company).casefold(), _normalize(item.title).casefold(), str(item.start_date)])
    if isinstance(item, SourcedProject):
        return _normalize(item.name).casefold()
    return "|".join([_normalize(item.school).casefold(), _normalize(item.major or "").casefold()])


def _validation_fields(error: ValidationError) -> list[str]:
    """把 Pydantic 错误压缩为稳定字段路径，不回传模型原始内容。"""
    return sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})


def _model_output_shape(value: object, *, depth: int = 0) -> object:
    """生成可安全写日志的模型输出形状，不包含简历、候选字段值或响应正文。

    只保留对象字段名、数组长度和标量类型，用于定位字段漂移或嵌套层级错误；对深层、过长
    数组和过多字段截断，避免异常响应本身放大日志体积。未知字段名可帮助识别契约漂移，
    但其值永远不会进入日志。
    """
    if depth >= 4:
        return {"type": type(value).__name__, "truncated": True}
    if isinstance(value, dict):
        mapping = cast("dict[object, object]", value)
        fields: list[str] = sorted(key for key in mapping if isinstance(key, str))
        visible_fields = fields[:50]
        result: dict[str, object] = {
            "type": "object",
            "fields": {key: _model_output_shape(mapping[key], depth=depth + 1) for key in visible_fields},
        }
        if len(fields) > len(visible_fields):
            result["omitted_field_count"] = len(fields) - len(visible_fields)
        if len(fields) != len(mapping):
            result["non_text_key_count"] = len(mapping) - len(fields)
        return result
    if isinstance(value, list):
        items = cast("list[object]", value)
        visible_items: list[object] = items[:20]
        result = {
            "type": "array",
            "length": len(items),
            "items": [_model_output_shape(item, depth=depth + 1) for item in visible_items],
        }
        if len(items) > len(visible_items):
            result["omitted_item_count"] = len(items) - len(visible_items)
        return result
    return {"type": type(value).__name__}


def _model_candidate_schema() -> dict[str, Any]:
    """返回发给模型的 JSON Schema：与候选契约一致，但**不含** `origin`。

    返回:
        dict[str, Any]: 去掉条目来源字段后的候选 Schema。

    注意:
        来源由服务端判定（模型只能产出"来自简历原文"的条目），所以它不该出现在模型契约里：
        留在 Schema 中会让模型每次都尝试填它，而服务端随后必须剥离并告警，结果是**每条候选**
        都挂一条无意义的警告、`completeness` 永远为 PARTIAL，真实问题反而被噪声淹没。
        客户端的确认契约仍然要求 `origin`（缺了就 422，失败关闭）。
    """
    schema = ImportCandidate.model_json_schema()
    raw_definitions = schema.get("$defs")
    if not isinstance(raw_definitions, dict):
        return schema
    definitions = cast("dict[str, Any]", raw_definitions)
    for name in ("SourcedSkill", "SourcedExperience", "SourcedProject", "SourcedEducation"):
        raw_item = definitions.get(name)
        if not isinstance(raw_item, dict):
            continue
        item = cast("dict[str, Any]", raw_item)
        properties = item.get("properties")
        if isinstance(properties, dict):
            cast("dict[str, Any]", properties).pop("origin", None)
        required = item.get("required")
        if isinstance(required, list):
            item["required"] = [field for field in cast("list[str]", required) if field != "origin"]
    return schema


def _parse_preview_candidate(
    result: dict[str, Any], text: str
) -> tuple[ImportCandidate, ImportPreviewCompleteness, list[ImportPreviewRejectedItem], list[ImportPreviewWarning]]:
    """从模型 JSON 构造可预览候选，并隔离集合条目的结构或证据失败。

    根信封仍使用 `extra=forbid`，以防模型改变整体契约。每个集合项会先剥离并报告
    未映射字段，再用原有严格 Pydantic 模型和原文规则验证；只有通过两层校验的条目进入
    `candidate`。因此确认接口永远不会收到未验证或未建模的模型字段。
    """
    try:
        root = _ImportCandidateRoot.model_validate(result)
    except ValidationError as error:
        logger.warning(
            "候选根信封校验失败",
            extra={
                "event": "profile_import_preview",
                "stage": "candidate_schema_failed",
                "validation_errors": [{"field": field, "type": "root_invalid"} for field in _validation_fields(error)],
            },
        )
        raise ValidationFailedError("AI 返回的档案候选格式无效，未写入个人档案。") from error

    item_models: dict[
        str, type[SourcedSkill] | type[SourcedExperience] | type[SourcedProject] | type[SourcedEducation]
    ] = {
        "skills": SourcedSkill,
        "experiences": SourcedExperience,
        "projects": SourcedProject,
        "educations": SourcedEducation,
    }
    group_names = {"skills": "skill", "experiences": "experience", "projects": "project", "educations": "education"}
    accepted: dict[str, list[Any]] = {key: [] for key in item_models}
    rejected: list[ImportPreviewRejectedItem] = []
    warnings: list[ImportPreviewWarning] = []

    for collection, model in item_models.items():
        raw_items = getattr(root, collection)
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict):
                rejected.append(
                    ImportPreviewRejectedItem(
                        group=collection,
                        index=index,
                        code="SCHEMA_INVALID",
                        message="该条目不是可识别的对象，未进入待确认列表。",
                    )
                )
                _log_candidate_invalid(group_names[collection], index, "schema_item_not_object")
                continue
            raw_object = cast("dict[object, object]", raw_item)
            if not all(isinstance(key, str) for key in raw_object):
                rejected.append(
                    ImportPreviewRejectedItem(
                        group=collection,
                        index=index,
                        code="SCHEMA_INVALID",
                        message="该条目的字段名不是有效文本，未进入待确认列表。",
                    )
                )
                _log_candidate_invalid(group_names[collection], index, "schema_item_invalid_key")
                continue
            raw_mapping = cast("dict[str, Any]", raw_object)
            if collection == "projects":
                # 归一化只修字段形态，不放松证据要求；发生归一化时对用户可见，避免静默改写。
                raw_mapping, alias_fields = _normalize_project_item(raw_mapping)
                if alias_fields:
                    warnings.append(
                        ImportPreviewWarning(
                            group=collection,
                            index=index,
                            code="FIELD_ALIAS_MAPPED",
                            fields=alias_fields,
                            message="模型使用了与本档案契约等价的字段名或字符串技术栈，已归一化后继续按原文摘录校验。",
                        )
                    )
                    logger.info(
                        "模型项目字段已归一化",
                        extra={
                            "event": "profile_import_candidate_alias_mapped",
                            "candidate_group": group_names[collection],
                            "candidate_index": index,
                            "fields": alias_fields,
                        },
                    )
            # 条目来源由服务端判定：模型只能产出"来自简历原文"的条目，不能自行声明"本人填写"
            # 来绕过摘录校验。模型若返回 origin，先剥离并留下可见提示。
            if "origin" in raw_mapping:
                raw_mapping = {key: value for key, value in raw_mapping.items() if key != "origin"}
                warnings.append(
                    ImportPreviewWarning(
                        group=collection,
                        index=index,
                        code="UNMAPPED_MODEL_FIELD",
                        fields=["origin"],
                        message="模型返回的条目来源字段已忽略：条目来源由服务端按原文校验结果判定。",
                    )
                )
                logger.info(
                    "模型试图声明条目来源",
                    extra={
                        "event": "profile_import_candidate_origin_ignored",
                        "candidate_group": group_names[collection],
                        "candidate_index": index,
                    },
                )
            supported_fields: set[str] = set(model.model_fields)
            unknown_fields: list[str] = sorted(set(raw_mapping) - supported_fields)
            normalized_item: dict[str, Any] = {
                key: value for key, value in raw_mapping.items() if key in supported_fields
            }
            # 提取阶段的一切条目都按简历原文来源校验：来源不是模型可以选择的字段。
            normalized_item["origin"] = "RESUME"
            if unknown_fields:
                warnings.append(
                    ImportPreviewWarning(
                        group=collection,
                        index=index,
                        code="UNMAPPED_MODEL_FIELD",
                        fields=unknown_fields,
                        message="模型返回了当前档案结构未支持的字段；这些字段未作为候选事实导入。",
                    )
                )
                logger.info(
                    "模型返回未映射字段",
                    extra={
                        "event": "profile_import_candidate_unmapped_fields",
                        "candidate_group": group_names[collection],
                        "candidate_index": index,
                        "fields": unknown_fields,
                    },
                )
            try:
                item = model.model_validate(normalized_item)
            except ValidationError as error:
                fields = _validation_fields(error)
                rejected.append(
                    ImportPreviewRejectedItem(
                        group=collection,
                        index=index,
                        code="SCHEMA_INVALID",
                        fields=fields,
                        message="该条目的字段格式不符合要求，未进入待确认列表。",
                    )
                )
                _log_candidate_invalid(group_names[collection], index, "schema_invalid", fields=fields)
                continue
            if isinstance(item, SourcedProject):
                try:
                    item, excluded_fields = _filter_unquoted_project_fields(item, text, index)
                except ValidationFailedError:
                    rejected.append(
                        ImportPreviewRejectedItem(
                            group=collection,
                            index=index,
                            code="EVIDENCE_INVALID",
                            message="该项目的名称或原文摘录无法逐字定位到简历原文，未进入待确认列表。",
                        )
                    )
                    continue
                if excluded_fields:
                    warnings.append(
                        ImportPreviewWarning(
                            group=collection,
                            index=index,
                            code="FIELD_NOT_IN_QUOTE",
                            fields=excluded_fields,
                            message="这些字段未能在项目原文摘录中逐字定位，未作为简历事实导入；可由本人补充。",
                        )
                    )
            try:
                _check_sourced_item(group_names[collection], index, item, text, allow_deviation=False)
            except ValidationFailedError:
                rejected.append(
                    ImportPreviewRejectedItem(
                        group=collection,
                        index=index,
                        code="EVIDENCE_INVALID",
                        message="该条目的字段或摘录无法逐字定位到简历原文，未进入待确认列表。",
                    )
                )
                continue
            accepted[collection].append(item)

    parsed_links, dropped_link_count = _parse_links(root.links)
    candidate = ImportCandidate(
        full_name=root.full_name,
        name_quote=root.name_quote,
        headline=root.headline,
        summary=root.summary,
        email=root.email,
        phone=root.phone,
        city=root.city,
        links=parsed_links,
        skills=accepted["skills"],
        experiences=accepted["experiences"],
        projects=accepted["projects"],
        educations=accepted["educations"],
    )
    # 基础资料与姓名是整个档案候选的锚点，不存在可安全保留的同级替代项，继续整体拒绝。
    _check_basics(candidate, text, allow_edits=False)
    # 个人简介与公开链接按字段级隔离：定位不到就留空，不让整份简历的可验证内容一起失败。
    candidate, excluded_basics = _filter_unquoted_basics(candidate, text)
    excluded_fields = set(excluded_basics)
    if dropped_link_count:
        excluded_fields.add("links")
    if excluded_fields:
        excluded_names = sorted(excluded_fields)
        warnings.append(
            ImportPreviewWarning(
                group="basics",
                index=0,
                code="FIELD_NOT_IN_QUOTE",
                fields=excluded_names,
                message="这些基本信息未能在简历原文中逐字定位或格式不可用，未作为简历事实导入；可由本人补充。",
            )
        )
        logger.info(
            "候选基本信息被清空",
            extra={
                "event": "profile_import_candidate_excluded_basics",
                "fields": excluded_names,
                "dropped_link_count": dropped_link_count,
            },
        )
    valid_item_count = sum(len(items) for items in accepted.values())
    unmapped_field_count = sum(
        len(warning.fields) for warning in warnings if warning.code == "UNMAPPED_MODEL_FIELD"
    )
    excluded_field_count = sum(
        len(warning.fields) for warning in warnings if warning.code == "FIELD_NOT_IN_QUOTE"
    )
    completeness = ImportPreviewCompleteness(
        status="PARTIAL" if rejected or warnings else "COMPLETE",
        valid_item_count=valid_item_count,
        rejected_item_count=len(rejected),
        unmapped_field_count=unmapped_field_count,
        excluded_field_count=excluded_field_count,
    )
    return candidate, completeness, rejected, warnings


async def preview(
    session: AsyncSession,
    upload: ResumeUpload,
    *,
    confirm_external: bool,
    on_progress: Callable[[str], Awaitable[None]] | None = None,
) -> ImportPreviewRead:
    """本地抽取后经明确同意调用默认模型，返回未落库候选。

    参数:
        session: 当前会话；仅用于解析默认模型，读取后立即结束事务再发起请求。
        upload: 上传的简历文件。
        confirm_external: 用户是否确认将提取文字发送到外部模型。
        on_progress: 可选阶段回调；只传固定阶段码，不传原文或候选内容。

    返回:
        ImportPreviewRead: 带原文摘录、等待人工核对的候选。

    异常:
        ValidationFailedError: 未确认发送，或模型返回的候选格式无效、摘录无法定位。
        ConflictError: 尚未配置默认模型，或凭据无法解密（夹具模式不会触发后者）。

    注意:
        开启 `profile_import_fixture` 时用内置样例文本与固定结果替代模型调用，因此不需要配置服务商；
        它只替换外部输入，候选仍要经过同一套 Schema 与原文校验，且返回值带 `fixture=True` 标记。
    """
    if not confirm_external:
        raise ValidationFailedError("请先确认将简历文字发送到已配置的大模型服务。")
    logger.info("导入预览开始", extra={"event": "profile_import_preview", "stage": "started"})
    try:
        document = await asyncio.to_thread(parse_document, upload)
    except ValidationFailedError:
        logger.warning("导入文档解析失败", extra={"event": "profile_import_preview", "stage": "document_parse_failed"})
        raise
    logger.info(
        "导入文档解析完成",
        extra={"event": "profile_import_preview", "stage": "document_parsed", "text_chars": len(document.text)},
    )
    if on_progress is not None:
        await on_progress("document_parsed")
    if _mock_extraction_enabled():
        # mock 模式：不解析默认模型、也不发起外部请求，因此不需要配置服务商与凭据。
        # 用样例文本替换校验语料，使固定结果与"文档"自洽；后续校验与真实抽取完全一致。
        document = replace(document, text=FIXTURE_TEXT, source_hash=FIXTURE_SOURCE_HASH)
        logger.warning(
            "导入预览使用内置 mock 抽取结果",
            extra={"event": "profile_import_preview", "stage": "fixture_enabled"},
        )
        if on_progress is not None:
            await on_progress("ai_request_started")
        result = mock_extract_profile()
        logger.info(
            "夹具候选已就绪",
            extra={
                "event": "profile_import_model_output_shape",
                "stage": "ai_response_parsed",
                "model_output_shape": _model_output_shape(result),
            },
        )
        if on_progress is not None:
            await on_progress("ai_response_parsed")
    else:
        try:
            config = await ai_service.resolve_default_model(session, get_settings())
        except ConflictError:
            logger.warning(
                "默认模型解析失败", extra={"event": "profile_import_preview", "stage": "model_resolution_failed"}
            )
            raise
        logger.info("默认模型已解析", extra={"event": "profile_import_preview", "stage": "model_resolved"})
        if on_progress is not None:
            await on_progress("model_resolved")
        # 解析默认模型开启新的读事务；等待网络前必须结束它（见 ADR 0002）。
        await session.rollback()
        logger.info("开始生成导入候选", extra={"event": "profile_import_preview", "stage": "ai_request_started"})
        if on_progress is not None:
            await on_progress("ai_request_started")
        input_data = {
            "resume_text": document.text,
            "rules": (
                "只提取原文明确出现的信息。每项提供原文中连续出现的 source_quote；"
                "缺失字段留空，禁止推断经历、项目、学历、技能和日期。"
                "工作经历没有明确开始年份时不要输出；仅有年份或年月时，日期中的缺失月份/日以 1 补位。"
                "职责与成果（responsibilities/achievements）只属于工作经历与项目经历两个分组，"
                "且仅在摘录能逐字覆盖时填写，否则留空。"
                "项目经历仅在原文明确出现项目名称时输出，可填 name、role、description、"
                "responsibilities、achievements、tech_stack、url 与起止日期；"
                "日期缺失就留空，不要用工作经历的日期代替。"
                "个人简介（summary）只复制原文中的自我描述段落，逐字照抄，不要润色或补写。"
                "公开链接（links）只输出原文中实际出现的地址，每项给出 label（原文里对该地址的称呼）"
                "与 url；地址可以不带协议前缀，但不要补全、猜测或改写域名。"
            ),
        }
        for attempt in range(1, MAX_PREVIEW_AI_ATTEMPTS + 1):
            try:
                result = await gateway.generate(
                    config,
                    "extract_profile_from_resume",
                    input_data,
                    _model_candidate_schema(),
                )
                break
            except gateway.TransientAiGatewayError:
                if attempt == MAX_PREVIEW_AI_ATTEMPTS:
                    logger.warning(
                        "候选生成短暂失败且重试耗尽",
                        extra={
                            "event": "profile_import_preview",
                            "stage": "ai_request_retry_exhausted",
                            "attempt": attempt,
                        },
                    )
                    raise
                logger.warning(
                    "候选生成发生短暂失败，将重试一次",
                    extra={"event": "profile_import_preview", "stage": "ai_request_retrying", "attempt": attempt},
                )
                if on_progress is not None:
                    await on_progress("ai_request_retrying")
                await asyncio.sleep(PREVIEW_RETRY_DELAY_SECONDS)
            except ValidationFailedError:
                logger.warning("候选生成失败", extra={"event": "profile_import_preview", "stage": "ai_request_failed"})
                raise
        else:  # pragma: no cover - range 与 break 的完备性保护。
            raise AssertionError("预览调用未产生结果")
        logger.info(
            "候选生成完成",
            extra={
                "event": "profile_import_model_output_shape",
                "stage": "ai_response_parsed",
                "model_output_shape": _model_output_shape(result),
            },
        )
        if on_progress is not None:
            await on_progress("ai_response_parsed")
    try:
        candidate, completeness, rejected_items, warnings = _parse_preview_candidate(result, document.text)
    except ValidationFailedError:
        logger.warning(
            "候选根信封或基本信息未通过校验",
            extra={"event": "profile_import_preview", "stage": "candidate_evidence_failed"},
        )
        raise
    logger.info(
        "导入预览完成",
        extra={
            "event": "profile_import_preview",
            "stage": "completed",
            "skill_count": len(candidate.skills),
            "experience_count": len(candidate.experiences),
            "project_count": len(candidate.projects),
            "education_count": len(candidate.educations),
            "rejected_item_count": completeness.rejected_item_count,
            "unmapped_field_count": completeness.unmapped_field_count,
        },
    )
    if on_progress is not None:
        await on_progress("candidate_validated")
    return ImportPreviewRead(
        filename=document.filename,
        source_hash=document.source_hash,
        candidate=candidate,
        completeness=completeness,
        rejected_items=rejected_items,
        warnings=warnings,
        fixture=_mock_extraction_enabled(),
    )


def _selected[T](items: list[T], indices: list[int]) -> list[T]:
    """拒绝重复或越界选择，避免客户端确认内容与预览不一致。"""
    if len(indices) != len(set(indices)) or any(
        type(index) is not int or index < 0 or index >= len(items) for index in indices
    ):
        raise ValidationFailedError("导入选择项无效，请重新预览文件。")
    return [items[index] for index in indices]


def _manual_item_summary(item: SourcedSkill | SourcedExperience | SourcedProject | SourcedEducation) -> str:
    """把本人填写的条目概括成一行，作为「本人陈述」证据的内容。

    参数:
        item: 本人新增或修订过的候选条目；类型本身决定摘要形态，无需再传分组名。

    返回:
        str: 一行说明；只包含用户确认过的字段值，不复制简历原文。

    注意:
        证据内容需要能让人看懂"这条事实的来源是用户自己填的"，因此按类型给出可读摘要，
        而不是把整个对象序列化进去。
    """
    if isinstance(item, SourcedSkill):
        return f"技能：{item.name}"
    if isinstance(item, SourcedExperience):
        end = item.end_date.isoformat() if item.end_date else "至今"
        return f"工作经历：{item.company} · {item.title}（{item.start_date.isoformat()} — {end}）"
    if isinstance(item, SourcedProject):
        return f"项目经历：{item.name} · {item.role}" if item.role else f"项目经历：{item.name}"
    parts = [part for part in (item.school, item.major, item.degree) if part]
    return "教育经历：" + " · ".join(parts)


def _project_description(item: SourcedProject) -> str | None:
    """把项目的说明、职责与成果合并成 Profile 侧的项目说明。

    参数:
        item: 项目候选。

    返回:
        str | None: 按段落拼接后的文本；三者都为空时返回 None。

    注意:
        Profile 的项目事实只有 `description` 一列，而简历里的项目常把职责与成果分开写；
        这里只做拼接，不生成任何原文之外的内容——三个字段各自都已通过逐字校验。
    """
    parts = [part.strip() for part in (item.description, item.responsibilities, item.achievements) if part]
    return "\n".join(parts) if parts else None


async def apply(session: AsyncSession, payload: ImportConfirmRequest) -> ImportApplyRead:
    """在单个事务中将用户确认的候选写入档案，已有基本信息不覆盖。

    参数:
        session: 当前会话。
        payload: 确认请求；候选可能已被用户在预览界面修正。

    返回:
        ImportApplyRead: 档案主键与各类事实的新增数量。

    异常:
        ValidationFailedError: 未确认、选择项越界、摘录无法定位到原文、日期顺序非法，
            或所选条目已全部存在于档案中。
        ConflictError: 文件在预览后发生变化。

    注意:
        修正过的条目（字段值超出原文摘录）改挂"本人陈述"证据，而不是简历证据：
        把改写过的内容挂在简历摘录下会伪造来源，破坏"结论可追溯到证据"。
        已有档案时只追加四类事实，`summary`/`links` 这类根信息不覆盖（前端会禁用这两个字段，
        避免用户填了却被静默丢弃）。
    """
    if not payload.confirmed:
        raise ValidationFailedError("请核对候选内容并确认后再写入。")
    document = await asyncio.to_thread(parse_document, payload)
    if _mock_extraction_enabled():
        # mock 模式下预览返回的是样例文本与样例哈希，确认时必须用同一份语料核对，
        # 否则一批固定摘录会被拿去和用户文件比对而全部失败（见 import_fixture 模块）。
        document = replace(document, text=FIXTURE_TEXT, source_hash=FIXTURE_SOURCE_HASH)
    if document.source_hash != payload.source_hash:
        raise ConflictError("文件已变化，请重新生成候选。")
    manual = _check_candidate(payload.candidate, document.text)
    # 选择项与原始下标配对：写入时要靠下标判断该条目挂哪条证据（简历摘录还是本人填写）。
    skill_items = list(
        zip(payload.skill_indices, _selected(payload.candidate.skills, payload.skill_indices), strict=True)
    )
    experience_items = list(
        zip(
            payload.experience_indices,
            _selected(payload.candidate.experiences, payload.experience_indices),
            strict=True,
        )
    )
    project_items = list(
        zip(payload.project_indices, _selected(payload.candidate.projects, payload.project_indices), strict=True)
    )
    education_items = list(
        zip(payload.education_indices, _selected(payload.candidate.educations, payload.education_indices), strict=True)
    )
    selection: list[tuple[str, list[tuple[int, Any]]]] = [
        ("skill", skill_items),
        ("experience", experience_items),
        ("project", project_items),
        ("education", education_items),
    ]
    # 同一次提交里重复的条目属于输入错误，先按字段指出，而不是写进去两条一样的记录。
    for group, items in selection:
        duplicates = _ensure_no_duplicate_items(group, items)
        if duplicates:
            raise ValidationFailedError("确认内容中存在重复条目，请先删除重复项。", details=duplicates)
    profile = await repo.get_profile(session)
    created_profile = profile is None
    if profile is None:
        # 建档时把候选的整份基本信息写进档案：字段与"创建个人档案"表单一一对应。
        profile = PersonalProfile(
            full_name=payload.candidate.full_name,
            headline=payload.candidate.headline,
            summary=payload.candidate.summary,
            email=payload.candidate.email,
            phone=payload.candidate.phone,
            city=payload.candidate.city,
            links=[link.model_dump() for link in payload.candidate.links],
        )
        session.add(profile)
        await session.flush()
    elif not any(items for _, items in selection):
        raise ValidationFailedError("现有档案没有选中可新增的条目。")

    resume_quotes = [payload.candidate.name_quote]
    manual_summaries: list[str] = []
    for group, items in selection:
        for index, item in items:
            if (group, index) in manual:
                manual_summaries.append(_manual_item_summary(item))
            elif item.source_quote:
                resume_quotes.append(item.source_quote)

    evidence = ProfileEvidence(
        profile_id=profile.id,
        source_type=EvidenceSourceType.RESUME_DOCUMENT,
        title=f"导入简历：{document.filename}"[:200],
        content="用户确认的来源摘录：\n" + "\n".join(dict.fromkeys(resume_quotes)),
        source_hash=document.source_hash,
        verification_status=VerificationStatus.UNVERIFIED,
    )
    session.add(evidence)
    await session.flush()
    manual_evidence: ProfileEvidence | None = None
    if manual_summaries:
        # 只有确实存在本人填写的条目时才建这条证据；它的来源是用户本人，因此不写入文件哈希。
        manual_evidence = ProfileEvidence(
            profile_id=profile.id,
            source_type=EvidenceSourceType.MANUAL_DECLARATION,
            title=f"导入本人填写：{document.filename}"[:200],
            content="用户在导入确认时新增或修订的条目（来源为本人陈述，不是简历原文）：\n"
            + "\n".join(dict.fromkeys(manual_summaries)),
            source_hash=None,
            verification_status=VerificationStatus.UNVERIFIED,
        )
        session.add(manual_evidence)
        await session.flush()

    def source_evidence(group: str, index: int) -> uuid.UUID:
        """按条目来源选择证据：本人填写的挂本人陈述，其余挂简历摘录。"""
        if manual_evidence is not None and (group, index) in manual:
            return manual_evidence.id
        return evidence.id

    existing_skills: set[str] = (
        {normalize_skill_name(item.name) for item in profile.skills} if not created_profile else set()
    )
    existing_experiences: set[tuple[str, str, date]] = (
        {(item.company.casefold(), item.title.casefold(), item.start_date) for item in profile.experiences}
        if not created_profile
        else set()
    )
    existing_projects: set[str] = (
        {item.name.casefold() for item in profile.projects} if not created_profile else set()
    )
    existing_educations: set[tuple[str, str]] = (
        {(item.school.casefold(), (item.major or "").casefold()) for item in profile.educations}
        if not created_profile
        else set()
    )
    counts = {"skills": 0, "experiences": 0, "projects": 0, "educations": 0}
    # 实际写入的条目里有多少条按「本人填写」记录来源；用于确认结果里如实说明归因（不改变可信度）。
    manual_written = 0
    for index, item in skill_items:
        key = normalize_skill_name(item.name)
        if key in existing_skills:
            continue
        existing_skills.add(key)
        session.add(
            ProfileSkill(
                profile_id=profile.id,
                name=item.name,
                name_normalized=key,
                source_evidence_id=source_evidence("skill", index),
                claim_status=ClaimStatus.UNVERIFIED,
                sort_order=counts["skills"],
            )
        )
        if ("skill", index) in manual:
            manual_written += 1
        counts["skills"] += 1
    for index, item in experience_items:
        key = (item.company.casefold(), item.title.casefold(), item.start_date)
        if key in existing_experiences:
            continue
        existing_experiences.add(key)
        session.add(
            ProfileExperience(
                profile_id=profile.id,
                company=item.company,
                title=item.title,
                location=item.location,
                start_date=item.start_date,
                end_date=item.end_date,
                responsibilities=item.responsibilities,
                achievements=item.achievements,
                source_evidence_id=source_evidence("experience", index),
                sort_order=counts["experiences"],
            )
        )
        if ("experience", index) in manual:
            manual_written += 1
        counts["experiences"] += 1
    for index, item in project_items:
        key = item.name.casefold()
        if key in existing_projects:
            continue
        existing_projects.add(key)
        session.add(
            ProfileProject(
                profile_id=profile.id,
                name=item.name,
                role=item.role,
                description=_project_description(item),
                tech_stack=item.tech_stack,
                url=item.url,
                start_date=item.start_date,
                end_date=item.end_date,
                source_evidence_id=source_evidence("project", index),
                sort_order=counts["projects"],
            )
        )
        if ("project", index) in manual:
            manual_written += 1
        counts["projects"] += 1
    for index, item in education_items:
        key = (item.school.casefold(), (item.major or "").casefold())
        if key in existing_educations:
            continue
        existing_educations.add(key)
        session.add(
            ProfileEducation(
                profile_id=profile.id,
                school=item.school,
                major=item.major,
                degree=item.degree,
                start_date=item.start_date,
                end_date=item.end_date,
                source_evidence_id=source_evidence("education", index),
                sort_order=counts["educations"],
            )
        )
        if ("education", index) in manual:
            manual_written += 1
        counts["educations"] += 1
    if not created_profile and not any(counts.values()):
        raise ValidationFailedError("所选条目已全部存在于档案中，没有新增内容。")
    profile_id = profile.id
    await session.commit()
    return ImportApplyRead(
        profile_id=str(profile_id),
        created_profile=created_profile,
        skills_added=counts["skills"],
        experiences_added=counts["experiences"],
        projects_added=counts["projects"],
        educations_added=counts["educations"],
        manual_item_count=manual_written,
    )
