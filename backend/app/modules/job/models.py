"""Job 领域的数据模型。

机会、平台页面与 JD 内容快照各自有独立生命周期：同一机会可能有多个页面，同一页面也会
随时间产生多份内容快照。快照不继承可编辑模型，防止后续匹配或申请引用的 JD 被改写。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    nature_code: Mapped[str | None] = mapped_column(String(40), comment="用户确认的公司性质代码。")
    industry_code: Mapped[str | None] = mapped_column(String(80), comment="用户确认的两级行业代码。")
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
    outsourcing_arrangement: Mapped[str | None] = mapped_column(
        String(32), comment="用户确认的岗位安排：OUTSOURCING、DIRECT 或未知。"
    )
    dedupe_key: Mapped[str | None] = mapped_column(
        String(256), index=True, comment="供后续人工去重辅助使用的键，不作为唯一约束。"
    )


class JobPosting(UuidPrimaryKeyMixin, EditableMixin, Base):
    """一个职位在某个来源上的页面标识。"""

    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_postings_source_external_id"),
        UniqueConstraint("source", "canonical_url", name="uq_job_postings_source_canonical_url"),
        ForeignKeyConstraint(
            ["id", "current_snapshot_id"],
            ["job_snapshots.posting_id", "job_snapshots.id"],
            name="fk_job_postings_current_snapshot",
            ondelete="RESTRICT",
            use_alter=True,
        ),
    )

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("job_opportunities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[JobSource] = mapped_column(enum_column_type(JobSource, "job_source"), nullable=False)
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
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
    __table_args__ = (
        UniqueConstraint("posting_id", "content_hash", name="uq_job_snapshots_posting_id_content_hash"),
        UniqueConstraint("posting_id", "id", name="uq_job_snapshots_posting_id_id"),
    )

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
    __table_args__ = (
        CheckConstraint(
            "(status = 'PARSED' AND result_json IS NOT NULL AND result_json <> 'null'::jsonb "
            "AND failure_code IS NULL) OR "
            "(status = 'FAILED' AND (result_json IS NULL OR result_json = 'null'::jsonb) AND failure_code IS NOT NULL)",
            name="parse_result_state",
        ),
    )
    job_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_snapshots.id", ondelete="RESTRICT"), index=True)
    parser_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    failure_code: Mapped[str | None] = mapped_column(String(64))


class JobImportCandidate(UuidPrimaryKeyMixin, EditableMixin, Base):
    """平台内容的待确认候选；原提取内容冻结，人工确认及产物在同一事务记录。"""

    __tablename__ = "job_import_candidates"
    __table_args__ = (
        CheckConstraint("source <> 'MANUAL'", name="platform_source"),
        CheckConstraint(
            "(target_posting_id IS NULL AND observed_posting_version IS NULL) OR "
            "(target_posting_id IS NOT NULL AND observed_posting_version IS NOT NULL "
            "AND observed_posting_version > 0)",
            name="observed_target",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND confirmed_posting_id IS NULL AND confirmed_snapshot_id IS NULL "
            "AND reviewed_json IS NULL) OR (status = 'CONFIRMED' AND confirmed_posting_id IS NOT NULL "
            "AND confirmed_snapshot_id IS NOT NULL AND reviewed_json IS NOT NULL "
            "AND reviewed_json <> 'null'::jsonb)",
            name="confirmation_state",
        ),
        ForeignKeyConstraint(
            ["confirmed_posting_id", "confirmed_snapshot_id"],
            ["job_snapshots.posting_id", "job_snapshots.id"],
            name="fk_job_import_candidates_confirmed_snapshot",
            ondelete="RESTRICT",
        ),
    )

    source: Mapped[JobSource] = mapped_column(enum_column_type(JobSource, "import_source"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False, comment="详情链接识别出的稳定职位 ID。")
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False, comment="去除跟踪参数的白名单详情地址。")
    input_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="用户提供内容的 SHA-256，不保存整个 HTML。"
    )
    extractor_version: Mapped[str] = mapped_column(String(64), nullable=False, comment="本地页面提取器版本。")
    candidate_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, comment="冻结的必要字段、正文摘录和警告。"
    )
    reviewed_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True),
        comment="明确确认的人工核对内容；与原候选一起保留。",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="待确认候选的过期时间。"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'PENDING'"))
    target_posting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job_postings.id", ondelete="RESTRICT"))
    observed_posting_version: Mapped[int | None] = mapped_column(
        Integer, comment="预览时页面版本；确认时防止覆盖新观察。"
    )
    confirmed_posting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job_postings.id", ondelete="RESTRICT"))
    confirmed_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))


class ExclusionPolicy(UuidPrimaryKeyMixin, EditableMixin, Base):
    """单人结构化排除策略；旧偏好标签保持独立且不执行。"""

    __tablename__ = "exclusion_policies"
    __table_args__ = (CheckConstraint("singleton_key = 'default'", name="singleton_default"),)
    singleton_key: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False, server_default=text("'default'")
    )
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class ExclusionEvaluation(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """一次输入版本固定的评估审计记录，重新评估产生新行。"""

    __tablename__ = "exclusion_evaluations"
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_opportunities.id", ondelete="RESTRICT"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_snapshots.id", ondelete="RESTRICT"))
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    company_version: Mapped[int] = mapped_column(Integer, nullable=False)
    opportunity_version: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class ExclusionException(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """用户明确确认的单职位临时例外；输入任一版本变化便失效。"""

    __tablename__ = "exclusion_exceptions"
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_opportunities.id", ondelete="RESTRICT"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_snapshots.id", ondelete="RESTRICT"))
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    company_version: Mapped[int] = mapped_column(Integer, nullable=False)
    opportunity_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
