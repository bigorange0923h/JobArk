"""Job 领域 API 的输入与输出模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.core.responses import EditableRead, ORMModel

from .enums import JobSource, OpportunityStatus, PostingStatus, SnapshotParseStatus


class CompanyCreate(BaseModel):
    """创建公司时可记录的已知信息。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200, description="公司显示名称。")
    website_url: HttpUrl | None = Field(default=None, max_length=2048, description="公司官网。")
    industry: str | None = Field(default=None, max_length=120, description="行业描述。")
    location: str | None = Field(default=None, max_length=200, description="公司所在地。")


class JobManualCreate(BaseModel):
    """一次手工职位录入请求；四张表在同一事务内创建。"""

    model_config = ConfigDict(extra="forbid")

    @field_validator("title", "raw_jd")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        """拒绝空白内容，同时原样保留 JD。"""
        if not value.strip():
            raise ValueError("内容不得全部为空白。")
        return value

    company: CompanyCreate
    title: str = Field(min_length=1, max_length=200, description="职位标题。")
    location: str | None = Field(default=None, max_length=200, description="职位地点。")
    employment_type: str | None = Field(default=None, max_length=80, description="雇佣类型。")
    notes: str | None = Field(default=None, max_length=10000, description="用户手工备注。")
    canonical_url: HttpUrl | None = Field(default=None, max_length=2048, description="招聘页面地址；可省略。")
    raw_jd: str = Field(min_length=1, max_length=100000, description="原始职位描述。")


class JobOpportunityUpdate(BaseModel):
    """可编辑职位机会的局部更新。"""

    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, description="当前乐观锁版本。")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    employment_type: str | None = Field(default=None, max_length=80)
    status: OpportunityStatus | None = None
    notes: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def require_change(self) -> JobOpportunityUpdate:
        """禁止只提交 version 的无意义写入。"""
        if not self.model_fields_set - {"version"}:
            raise ValueError("至少提供一个需要更新的字段。")
        if "title" in self.model_fields_set and (self.title is None or not self.title.strip()):
            raise ValueError("职位标题不能为空。")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("状态不能为空。")
        return self


class JobSnapshotCreate(BaseModel):
    """为现有职位页面保存新的 JD 内容快照。"""

    raw_jd: str = Field(min_length=1, max_length=100000, description="原始职位描述。")

    @field_validator("raw_jd")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        """拒绝空白 JD，保留原文。"""
        if not value.strip():
            raise ValueError("JD 不得全部为空白。")
        return value


class CompanyRead(EditableRead):
    """公司响应。"""

    name: str
    name_normalized: str
    website_url: str | None
    industry: str | None
    nature_code: str | None
    industry_code: str | None
    location: str | None


class JobPostingRead(EditableRead):
    """职位页面响应。"""

    current_snapshot_id: UUID | None = Field(description="页面当前内容；重复观察可指向旧快照。")
    opportunity_id: UUID
    source: JobSource
    external_id: str | None
    canonical_url: str | None
    first_seen_at: datetime = Field(description="系统首次发现该来源的时间，不是平台发布时间。")
    last_seen_at: datetime = Field(description="系统最近接收该来源内容的时间；手工保存或导入，不表示平台扫描成功。")
    page_status: PostingStatus


class JobSnapshotRead(ORMModel):
    """不可变 JD 快照响应。"""

    id: UUID
    posting_id: UUID
    content_hash: str
    captured_at: datetime = Field(description="该来源下此 JD 内容首次采集时间；复用旧内容时保持不变。")
    raw_jd: str
    parsed_json: dict[str, object] | None
    parse_status: SnapshotParseStatus
    parser_version: str | None
    failure_code: str | None
    created_at: datetime


class JobOpportunityRead(EditableRead):
    """职位机会聚合响应。"""

    company: CompanyRead
    title: str
    location: str | None
    employment_type: str | None
    status: OpportunityStatus
    notes: str | None
    outsourcing_arrangement: str | None
    postings: list[JobPostingRead]
    latest_snapshot: JobSnapshotRead | None = Field(
        description=(
            "兼容字段：从有当前快照的来源按 last_seen_at DESC、id DESC 选取；"
            "posting_id 标识采用来源，不代表平台实时最新。"
        )
    )


class JobListItem(EditableRead):
    """职位列表项；保留当前快照摘要而不重复传输完整 JD。"""

    company_name: str
    title: str
    location: str | None
    employment_type: str | None
    status: OpportunityStatus
    latest_snapshot_id: UUID | None = Field(
        description="兼容字段：当前保存 JD 的快照 ID；无当前内容时为空，不以历史兜底。"
    )
    latest_captured_at: datetime | None = Field(
        description="兼容字段：当前 JD 内容首次采集时间，不是最近接收或平台发布时间。"
    )
