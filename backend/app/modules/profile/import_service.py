"""简历文档导入：只把可回溯的 AI 候选经人工确认后写入 Profile。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from io import BytesIO
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai_service
from app.ai.llm import gateway
from app.core.config import get_settings
from app.core.errors import ConflictError, ValidationFailedError

from . import repository as repo
from .enums import ClaimStatus, EvidenceSourceType, VerificationStatus
from .models import PersonalProfile, ProfileEducation, ProfileEvidence, ProfileExperience, ProfileSkill
from .service import normalize_skill_name

MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_PDF_PAGES = 10
MAX_TEXT_CHARS = 40_000


class ResumeUpload(BaseModel):
    """上传文档的 JSON 传输体；限制 base64 长度避免大文件占用过多内存。"""

    filename: str = Field(min_length=1, max_length=200, description="原始文件名，仅用于判断格式和显示来源。")
    content_base64: str = Field(min_length=1, max_length=4_200_000, description="PDF/HTML 文件的 base64 内容。")


class SourcedSkill(BaseModel):
    """带原文摘录的技能候选，不代表已验证能力。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    source_quote: str = Field(min_length=1, max_length=500)


class SourcedExperience(BaseModel):
    """带原文摘录的工作经历候选。"""

    model_config = ConfigDict(extra="forbid")
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date | None = None
    location: str | None = Field(default=None, max_length=100)
    responsibilities: str | None = Field(default=None, max_length=3000)
    achievements: str | None = Field(default=None, max_length=3000)
    source_quote: str = Field(min_length=1, max_length=500)


class SourcedEducation(BaseModel):
    """带原文摘录的教育经历候选。"""

    model_config = ConfigDict(extra="forbid")
    school: str = Field(min_length=1, max_length=200)
    major: str | None = Field(default=None, max_length=200)
    degree: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    source_quote: str = Field(min_length=1, max_length=500)


class ImportCandidate(BaseModel):
    """未确认的档案候选；只覆盖可从简历明确提取的基本信息和三类事实。"""

    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1, max_length=100)
    name_quote: str = Field(min_length=1, max_length=500)
    headline: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=100)
    skills: list[SourcedSkill] = Field(default_factory=list[SourcedSkill], max_length=40)
    experiences: list[SourcedExperience] = Field(default_factory=list[SourcedExperience], max_length=20)
    educations: list[SourcedEducation] = Field(default_factory=list[SourcedEducation], max_length=20)


class ImportPreviewRead(BaseModel):
    """供用户核对、选择的候选；原文文件不会保存在服务端。"""

    filename: str
    source_hash: str
    candidate: ImportCandidate


class ImportConfirmRequest(ResumeUpload):
    """确认写入时重传原文件，防止客户端把未经验证的候选单独提交。"""

    source_hash: str = Field(min_length=64, max_length=64)
    candidate: ImportCandidate
    skill_indices: list[int] = Field(default_factory=list[int], max_length=40)
    experience_indices: list[int] = Field(default_factory=list[int], max_length=20)
    education_indices: list[int] = Field(default_factory=list[int], max_length=20)
    confirmed: bool = Field(description="用户已逐项核对并确认写入。")


class ImportApplyRead(BaseModel):
    """确认导入的结果；已有档案不会被覆盖。"""

    profile_id: str
    created_profile: bool
    skills_added: int
    experiences_added: int
    educations_added: int


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


def _check_candidate(candidate: ImportCandidate, text: str) -> None:
    """拒绝无法定位到原文的条目；摘录不等于已核验事实。"""
    groups: list[tuple[str, list[str | None]]] = [(candidate.name_quote, [candidate.full_name])]
    groups.extend((item.source_quote, [item.name]) for item in candidate.skills)
    groups.extend(
        (
            item.source_quote,
            [item.company, item.title, item.location, item.responsibilities, item.achievements],
        )
        for item in candidate.experiences
    )
    groups.extend((item.source_quote, [item.school, item.major, item.degree]) for item in candidate.educations)
    for quote, values in groups:
        normalized_quote = _normalize(quote)
        if normalized_quote not in text or any(_normalize(value) not in normalized_quote for value in values if value):
            raise ValidationFailedError("候选内容无法逐字定位到简历原文，未写入个人档案。")
    if any(
        _normalize(value) not in text
        for value in (candidate.headline, candidate.email, candidate.phone, candidate.city)
        if value
    ):
        raise ValidationFailedError("候选基本信息无法逐字定位到简历原文，未写入个人档案。")
    for item in [*candidate.experiences, *candidate.educations]:
        for item_date in (item.start_date, item.end_date):
            if item_date and str(item_date.year) not in item.source_quote:
                raise ValidationFailedError("候选日期未出现在对应原文摘录中，未写入个人档案。")
    if any(item.end_date is not None and item.end_date < item.start_date for item in candidate.experiences):
        raise ValidationFailedError("工作经历的结束日期早于开始日期，未写入个人档案。")
    if any(item.start_date and item.end_date and item.end_date < item.start_date for item in candidate.educations):
        raise ValidationFailedError("教育经历的结束日期早于开始日期，未写入个人档案。")


async def preview(session: AsyncSession, upload: ResumeUpload, *, confirm_external: bool) -> ImportPreviewRead:
    """本地抽取后经明确同意调用默认模型，返回未落库候选。

    参数:
        session: 当前会话；仅用于解析默认模型，读取后立即结束事务再发起请求。
        upload: 上传的简历文件。
        confirm_external: 用户是否确认将提取文字发送到外部模型。

    返回:
        ImportPreviewRead: 带原文摘录、等待人工核对的候选。

    异常:
        ValidationFailedError: 未确认发送，或模型返回的候选格式无效、摘录无法定位。
        ConflictError: 尚未配置默认模型，或凭据无法解密。
    """
    if not confirm_external:
        raise ValidationFailedError("请先确认将简历文字发送到已配置的 AI 网关。")
    document = await asyncio.to_thread(parse_document, upload)
    config = await ai_service.resolve_default_model(session, get_settings())
    # 解析默认模型开启新的读事务；等待网络前必须结束它（见 ADR 0002）。
    await session.rollback()
    result = await gateway.generate(
        config,
        "extract_profile_from_resume",
        {
            "resume_text": document.text,
            "rules": (
                "只提取原文明确出现的信息。每项提供原文中连续出现的 source_quote；"
                "缺失字段留空，禁止推断经历、学历、技能和日期。"
                "工作经历没有明确开始年份时不要输出；仅有年份或年月时，日期中的缺失月份/日以 1 补位。"
                "职责和成果仅在摘录能逐字覆盖时填写，否则留空。"
            ),
        },
        ImportCandidate.model_json_schema(),
    )
    try:
        candidate = ImportCandidate.model_validate(result)
    except ValidationError as error:
        raise ValidationFailedError("AI 返回的档案候选格式无效，未写入个人档案。") from error
    _check_candidate(candidate, document.text)
    return ImportPreviewRead(filename=document.filename, source_hash=document.source_hash, candidate=candidate)


def _selected[T](items: list[T], indices: list[int]) -> list[T]:
    """拒绝重复或越界选择，避免客户端确认内容与预览不一致。"""
    if len(indices) != len(set(indices)) or any(
        type(index) is not int or index < 0 or index >= len(items) for index in indices
    ):
        raise ValidationFailedError("导入选择项无效，请重新预览文件。")
    return [items[index] for index in indices]


async def apply(session: AsyncSession, payload: ImportConfirmRequest) -> ImportApplyRead:
    """在单个事务中将用户确认的候选写入档案，已有基本信息不覆盖。"""
    if not payload.confirmed:
        raise ValidationFailedError("请核对候选内容并确认后再写入。")
    document = await asyncio.to_thread(parse_document, payload)
    if document.source_hash != payload.source_hash:
        raise ConflictError("文件已变化，请重新生成候选。")
    _check_candidate(payload.candidate, document.text)
    skills = _selected(payload.candidate.skills, payload.skill_indices)
    experiences = _selected(payload.candidate.experiences, payload.experience_indices)
    educations = _selected(payload.candidate.educations, payload.education_indices)
    profile = await repo.get_profile(session)
    created_profile = profile is None
    if profile is None:
        profile = PersonalProfile(
            full_name=payload.candidate.full_name,
            headline=payload.candidate.headline,
            email=payload.candidate.email,
            phone=payload.candidate.phone,
            city=payload.candidate.city,
            links=[],
        )
        session.add(profile)
        await session.flush()
    elif not (skills or experiences or educations):
        raise ValidationFailedError("现有档案没有选中可新增的条目。")
    quotes = [payload.candidate.name_quote]
    quotes.extend(item.source_quote for item in [*skills, *experiences, *educations])
    evidence = ProfileEvidence(
        profile_id=profile.id,
        source_type=EvidenceSourceType.RESUME_DOCUMENT,
        title=f"导入简历：{document.filename}"[:200],
        content="用户确认的来源摘录：\n" + "\n".join(dict.fromkeys(quotes)),
        source_hash=document.source_hash,
        verification_status=VerificationStatus.UNVERIFIED,
    )
    session.add(evidence)
    await session.flush()
    existing_skills: set[str] = (
        {normalize_skill_name(item.name) for item in profile.skills} if not created_profile else set()
    )
    existing_experiences: set[tuple[str, str, date]] = (
        {(item.company.casefold(), item.title.casefold(), item.start_date) for item in profile.experiences}
        if not created_profile
        else set()
    )
    existing_educations: set[tuple[str, str]] = (
        {(item.school.casefold(), (item.major or "").casefold()) for item in profile.educations}
        if not created_profile
        else set()
    )
    counts = {"skills": 0, "experiences": 0, "educations": 0}
    for item in skills:
        key = normalize_skill_name(item.name)
        if key in existing_skills:
            continue
        existing_skills.add(key)
        session.add(
            ProfileSkill(
                profile_id=profile.id,
                name=item.name,
                name_normalized=key,
                source_evidence_id=evidence.id,
                claim_status=ClaimStatus.UNVERIFIED,
                sort_order=counts["skills"],
            )
        )
        counts["skills"] += 1
    for item in experiences:
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
                source_evidence_id=evidence.id,
                sort_order=counts["experiences"],
            )
        )
        counts["experiences"] += 1
    for item in educations:
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
                source_evidence_id=evidence.id,
                sort_order=counts["educations"],
            )
        )
        counts["educations"] += 1
    if not created_profile and not any(counts.values()):
        raise ValidationFailedError("所选条目已全部存在于档案中，没有新增内容。")
    await session.commit()
    return ImportApplyRead(
        profile_id=str(profile.id),
        created_profile=created_profile,
        skills_added=counts["skills"],
        experiences_added=counts["experiences"],
        educations_added=counts["educations"],
    )
