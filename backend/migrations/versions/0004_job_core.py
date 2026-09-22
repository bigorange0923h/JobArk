"""job core：公司、职位机会、页面与不可变 JD 快照

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-22

对应数据模型的第三组迁移。页面与内容快照分表，避免后续页面更新覆盖已经被匹配或申请
引用的 JD；本修订只保存人工输入的原始 JD，不接入任何会伪造结构化信息的解析流程。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """升级到 Job 核心数据表。"""
    op.create_table(
        "companies",
        sa.Column("name", sa.String(length=200), nullable=False, comment="公司显示名称。"),
        sa.Column("name_normalized", sa.String(length=200), nullable=False, comment="用于检索的规范化名称。"),
        sa.Column("website_url", sa.String(length=2048), nullable=True, comment="公司官网；不用于自动判定公司唯一性。"),
        sa.Column("industry", sa.String(length=120), nullable=True, comment="行业描述。"),
        sa.Column("location", sa.String(length=200), nullable=True, comment="公司所在地或主要办公地。"),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间（UTC），由 ORM 在更新时刷新。"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False, comment="乐观锁版本号；每次更新自增，接口提交旧值即返回 409。"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="记录创建时间（UTC）。"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
    )
    op.create_index(op.f("ix_companies_name_normalized"), "companies", ["name_normalized"], unique=False)
    op.create_table(
        "job_opportunities",
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, comment="职位标题。"),
        sa.Column("location", sa.String(length=200), nullable=True, comment="职位地点。"),
        sa.Column("employment_type", sa.String(length=80), nullable=True, comment="雇佣类型，例如全职或实习。"),
        sa.Column("status", sa.Enum("ACTIVE", "ARCHIVED", name="opportunity_status", native_enum=False, create_constraint=True, length=32), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True, comment="用户手工备注；不承载页面原始内容。"),
        sa.Column("dedupe_key", sa.String(length=256), nullable=True, comment="供后续人工去重辅助使用的键，不作为唯一约束。"),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间（UTC），由 ORM 在更新时刷新。"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False, comment="乐观锁版本号；每次更新自增，接口提交旧值即返回 409。"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="记录创建时间（UTC）。"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_job_opportunities_company_id_companies"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_opportunities")),
    )
    op.create_index(op.f("ix_job_opportunities_company_id"), "job_opportunities", ["company_id"], unique=False)
    op.create_index(op.f("ix_job_opportunities_dedupe_key"), "job_opportunities", ["dedupe_key"], unique=False)
    op.create_table(
        "job_postings",
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.Enum("MANUAL", name="job_source", native_enum=False, create_constraint=True, length=32), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=True, comment="来源平台的职位标识；手工录入可为空。"),
        sa.Column("canonical_url", sa.String(length=2048), nullable=True, comment="规范化页面地址；手工录入可为空。"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("page_status", sa.Enum("ACTIVE", "UNAVAILABLE", name="posting_status", native_enum=False, create_constraint=True, length=32), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间（UTC），由 ORM 在更新时刷新。"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False, comment="乐观锁版本号；每次更新自增，接口提交旧值即返回 409。"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="记录创建时间（UTC）。"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["job_opportunities.id"], name=op.f("fk_job_postings_opportunity_id_job_opportunities"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_postings")),
        sa.UniqueConstraint("source", "external_id", name="uq_job_postings_source_external_id"),
        sa.UniqueConstraint("source", "canonical_url", name="uq_job_postings_source_canonical_url"),
    )
    op.create_index(op.f("ix_job_postings_opportunity_id"), "job_postings", ["opportunity_id"], unique=False)
    op.create_table(
        "job_snapshots",
        sa.Column("posting_id", sa.UUID(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, comment="原始 JD UTF-8 内容的 SHA-256。"),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="内容录入或抓取时间（UTC）。"),
        sa.Column("raw_jd", sa.Text(), nullable=False, comment="原始 JD；解析失败时仍完整保留。"),
        sa.Column("parsed_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="可信解析器的结构化结果；未解析或失败时为空。"),
        sa.Column("parse_status", sa.Enum("NOT_REQUESTED", "PARSED", "FAILED", name="snapshot_parse_status", native_enum=False, create_constraint=True, length=32), server_default=sa.text("'NOT_REQUESTED'"), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=True, comment="产生 parsed_json 的解析器版本。"),
        sa.Column("failure_code", sa.String(length=64), nullable=True, comment="安全错误码；不保存上游原始错误。"),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="记录创建时间（UTC）。"),
        sa.ForeignKeyConstraint(["posting_id"], ["job_postings.id"], name=op.f("fk_job_snapshots_posting_id_job_postings"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_snapshots")),
        sa.UniqueConstraint("posting_id", "content_hash", name="uq_job_snapshots_posting_id_content_hash"),
    )
    op.create_index(op.f("ix_job_snapshots_posting_id"), "job_snapshots", ["posting_id"], unique=False)


def downgrade() -> None:
    """回退 Job 核心数据表。"""
    op.drop_index(op.f("ix_job_snapshots_posting_id"), table_name="job_snapshots")
    op.drop_table("job_snapshots")
    op.drop_index(op.f("ix_job_postings_opportunity_id"), table_name="job_postings")
    op.drop_table("job_postings")
    op.drop_index(op.f("ix_job_opportunities_dedupe_key"), table_name="job_opportunities")
    op.drop_index(op.f("ix_job_opportunities_company_id"), table_name="job_opportunities")
    op.drop_table("job_opportunities")
    op.drop_index(op.f("ix_companies_name_normalized"), table_name="companies")
    op.drop_table("companies")
