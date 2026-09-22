"""Job 领域的数据模型。

机会、平台页面与 JD 内容快照各自有独立生命周期：同一机会可能有多个页面，同一页面也会
随时间产生多份内容快照。快照不继承可编辑模型，防止后续匹配或申请引用的 JD 被改写。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import CreatedAtMixin, EditableMixin, UuidPrimaryKeyMixin, enum_column_type

from .enums import JobSource, OpportunityStatus, PostingStatus, SnapshotParseStatus


class Company(UuidPrimaryKeyMixin, EditableMixin, Base):
    """招聘公司实体。

    规范化名称仅用于显示与后续人工辅助检索，刻意不设置全局唯一约束：同名公司可能并非同一
    法人，自动合并会让用户无法可靠地拆分历史机会。
    """

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="公司显示名称。")
    name_normalized: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True, comment="用于检索的规范化名称。"
    )
    website_url: Mapped[str | None] = mapped_column(String(2048), comment="公司官网；不用于自动判定公司唯一性。")
    industry: Mapped[str | None] = mapped_column(String(120), comment="行业描述。")
    location: Mapped[str | None] = mapped_column(String(200), comment="公司所在地或主要办公地。")


class JobOpportunity(UuidPrimaryKeyMixin, EditableMixin, Base):
    """一个可人工维护的职位机会，而非某个招聘页面。"""

    __tablename__ = "job_opportunities"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="职位标题。")
    location: Mapped[str | None] = mapped_column(String(200), comment="职位地点。")
    employment_type: Mapped[str | None] = mapped_column(String(80), comment="雇佣类型，例如全职或实习。")
    status: Mapped[OpportunityStatus] = mapped_column(
        enum_column_type(OpportunityStatus, "opportunity_status"), nullable=False, server_default=text("'ACTIVE'")
    )
    notes: Mapped[str | None] = mapped_column(Text, comment="用户手工备注；不承载页面原始内容。")
    dedupe_key: Mapped[str | None] = mapped_column(
        String(256), index=True, comment="供后续人工去重辅助使用的键，不作为唯一约束。"
    )


class JobPosting(UuidPrimaryKeyMixin, EditableMixin, Base):
    """一个职位在某个来源上的页面标识。"""

    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_postings_source_external_id"),
        UniqueConstraint("source", "canonical_url", name="uq_job_postings_source_canonical_url"),
    )

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("job_opportunities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[JobSource] = mapped_column(enum_column_type(JobSource, "job_source"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200), comment="来源平台的职位标识；手工录入可为空。")
    canonical_url: Mapped[str | None] = mapped_column(String(2048), comment="规范化页面地址；手工录入可为空。")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    page_status: Mapped[PostingStatus] = mapped_column(
        enum_column_type(PostingStatus, "posting_status"), nullable=False, server_default=text("'ACTIVE'")
    )


class JobSnapshot(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """不可变的某次 JD 内容快照。"""

    __tablename__ = "job_snapshots"
    __table_args__ = (UniqueConstraint("posting_id", "content_hash", name="uq_job_snapshots_posting_id_content_hash"),)

    posting_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("job_postings.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="原始 JD UTF-8 内容的 SHA-256。")
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), comment="内容录入或抓取时间（UTC）。"
    )
    raw_jd: Mapped[str] = mapped_column(Text, nullable=False, comment="原始 JD；解析失败时仍完整保留。")
    parsed_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="可信解析器的结构化结果；未解析或失败时为空。"
    )
    parse_status: Mapped[SnapshotParseStatus] = mapped_column(
        enum_column_type(SnapshotParseStatus, "snapshot_parse_status"),
        nullable=False,
        server_default=text("'NOT_REQUESTED'"),
    )
    parser_version: Mapped[str | None] = mapped_column(String(64), comment="产生 parsed_json 的解析器版本。")
    failure_code: Mapped[str | None] = mapped_column(String(64), comment="安全错误码；不保存上游原始错误。")


class JobParseResult(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """独立不可变解析产物，重试生成新记录，不修改 JD 历史。"""

    __tablename__ = "job_parse_results"
    job_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_snapshots.id", ondelete="RESTRICT"), index=True)
    parser_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    failure_code: Mapped[str | None] = mapped_column(String(64))
