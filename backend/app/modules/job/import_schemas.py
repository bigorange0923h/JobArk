"""招聘平台本地内容导入契约；来源身份由服务端 URL 适配器确定。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.responses import EditableRead

from .enums import JobSource


class ImportFields(BaseModel):
    """必要的职位内容；候选允许缺失公司和标题，确认模型负责必填校验。"""

    model_config = ConfigDict(extra="forbid")
    company_name: str = Field(max_length=200, description="来源公司名；未知为空，不推断公司分类。")
    title: str = Field(max_length=200, description="职位标题；未知为空。")
    location: str | None = Field(default=None, max_length=200, description="页面中明确的地点；可空。")
    raw_jd: str = Field(min_length=1, max_length=100000, description="必要的 JD 正文，不保存网页脚本或整个 HTML。")

    @field_validator("company_name", "title", "location", "raw_jd")
    @classmethod
    def valid_text(cls, value: str | None) -> str | None:
        """拒绝无法存储的 NUL 与无效 Unicode，不能让不可信页面引发数据库编码错误。"""
        if value is not None:
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as error:
                raise ValueError("内容存在无效字符，请重新复制并核对。") from error
            if "\x00" in value:
                raise ValueError("内容包含无效空字符，请重新复制并核对。")
        return value


class ImportPreview(BaseModel):
    """只处理用户提供内容，不访问网址，不外发 AI。"""

    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048, description="四个平台之一的 HTTPS 职位详情链接。")
    mode: Literal["HTML", "TEXT"] = Field(description="HTML 页面或用户复制的可见正文。")
    content: str = Field(min_length=1, max_length=1048576, description="待本地提取的内容，UTF-8 大小最多 1 MiB。")

    @field_validator("content")
    @classmethod
    def content_limit(cls, value: str) -> str:
        """按真实 UTF-8 字节限制输入，拒绝空内容；不改变输入哈希依据。"""
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ValueError("内容存在无效字符，请重新复制职位正文。") from error
        if not value.strip() or size > 1048576:
            raise ValueError("内容为空或超过 1 MiB，请只提供单个职位正文。")
        return value


class ImportConfirm(BaseModel):
    """明确确认后的人工内容；不能由请求改写平台或外部 ID。"""

    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, description="预览候选版本，过期版本返回 409。")
    confirm: bool = Field(strict=True, description="用户明确确认写入本地职位，不代表外部投递。")
    fields: ImportFields = Field(description="用户核对并修正的必要内容。")

    @field_validator("fields")
    @classmethod
    def required_fields(cls, value: ImportFields) -> ImportFields:
        """正式写入要求公司、标题和正文；只规范名称与地点，JD 忠实保留。"""
        if not value.company_name.strip() or not value.title.strip() or not value.raw_jd.strip():
            raise ValueError("请补全公司、职位标题和 JD 正文。")
        return value.model_copy(
            update={
                "company_name": value.company_name.strip(),
                "title": value.title.strip(),
                "location": value.location.strip() or None if value.location is not None else None,
            }
        )


class ImportRead(EditableRead):
    """候选与确认产物；原候选始终保留，人工修订单独显示。"""

    source: JobSource = Field(description="服务端依据白名单 URL 识别的平台，候选不使用 MANUAL。")
    external_id: str = Field(description="从详情 URL 提取的稳定职位 ID，只读。")
    canonical_url: str = Field(description="去除跟踪参数的详情 URL，只读，不由后端访问。")
    status: Literal["PENDING", "CONFIRMED"] = Field(description="待确认或已确认；过期不删除原候选。")
    expires_at: datetime = Field(description="待确认有效期，预览后 24 小时；已确认回执不受此限制。")
    extractor_version: str = Field(description="本地内容适配器版本，不代表真实平台抓取已验证。")
    fields: ImportFields = Field(description="冻结的预览字段；已有页面的公司/职位/地点沿用本地值。")
    warnings: list[str] = Field(description="缺失字段和需要人工核对的边界提示。")
    target_posting_id: UUID | None = Field(description="预览时已存在的页面；为空表示预期新建。")
    observed_posting_version: int | None = Field(description="预览时的页面版本，确认时用于防止覆盖新 JD。")
    confirmed_posting_id: UUID | None = Field(description="确认产物页面，PENDING 时为空。")
    confirmed_snapshot_id: UUID | None = Field(description="确认时保存或复用的快照，必须属于确认页面。")
    reviewed_fields: ImportFields | None = Field(description="人工确认的内容，保留与原预览的区别；待确认时为空。")


class ImportConfirmation(BaseModel):
    """不可变确认回执；重试仍返回本候选的原始产物，不回读后续 JD。"""

    opportunity_id: UUID = Field(description="本次确认关联的职位机会。")
    posting_id: UUID = Field(description="本次确认关联的平台页面。")
    snapshot_id: UUID = Field(description="本次确认保存或复用的不可变 JD 快照。")
