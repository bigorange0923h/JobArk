"""增加招聘平台来源与独立待确认内容；不迁移、抓取或覆盖现有职位。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCES = "source IN ('MANUAL','LINKEDIN','INDEED','BOSS','FIFTYONEJOB')"


def upgrade() -> None:
    """只扩展来源并建立候选表；候选不是正式职位事实。"""
    op.drop_constraint(op.f("ck_job_postings_job_source"), "job_postings", type_="check")
    op.create_check_constraint("job_source", "job_postings", SOURCES)
    op.create_table(
        "job_import_candidates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"), comment="记录创建时间（UTC）。"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"), comment="最后更新时间（UTC），由 ORM 在更新时刷新。"),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1"), comment="乐观锁版本号；每次更新自增，接口提交旧值即返回 409。"),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False, comment="详情链接识别出的稳定职位 ID。"),
        sa.Column("canonical_url", sa.String(2048), nullable=False, comment="去除跟踪参数的白名单详情地址。"),
        sa.Column("input_hash", sa.String(64), nullable=False, comment="用户提供内容的 SHA-256，不保存整个 HTML。"),
        sa.Column("extractor_version", sa.String(64), nullable=False, comment="本地页面提取器版本。"),
        sa.Column("candidate_json", postgresql.JSONB(), nullable=False, comment="冻结的必要字段、正文摘录和警告。"),
        sa.Column("reviewed_json", postgresql.JSONB(), nullable=True, comment="明确确认的人工核对内容；与原候选一起保留。"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, comment="待确认候选的过期时间。"),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("target_posting_id", sa.UUID(), nullable=True),
        sa.Column("observed_posting_version", sa.Integer(), nullable=True, comment="预览时页面版本；确认时防止覆盖新观察。"),
        sa.Column("confirmed_posting_id", sa.UUID(), nullable=True),
        sa.Column("confirmed_snapshot_id", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_import_candidates")),
        sa.CheckConstraint(SOURCES, name=op.f("ck_job_import_candidates_import_source")),
        sa.CheckConstraint("source <> 'MANUAL'", name=op.f("ck_job_import_candidates_platform_source")),
        sa.CheckConstraint("(target_posting_id IS NULL AND observed_posting_version IS NULL) OR (target_posting_id IS NOT NULL AND observed_posting_version IS NOT NULL AND observed_posting_version > 0)", name=op.f("ck_job_import_candidates_observed_target")),
        sa.CheckConstraint("(status = 'PENDING' AND confirmed_posting_id IS NULL AND confirmed_snapshot_id IS NULL AND reviewed_json IS NULL) OR (status = 'CONFIRMED' AND confirmed_posting_id IS NOT NULL AND confirmed_snapshot_id IS NOT NULL AND reviewed_json IS NOT NULL AND reviewed_json <> 'null'::jsonb)", name=op.f("ck_job_import_candidates_confirmation_state")),
        sa.ForeignKeyConstraint(["target_posting_id"], ["job_postings.id"], ondelete="RESTRICT", name=op.f("fk_job_import_candidates_target_posting_id_job_postings")),
        sa.ForeignKeyConstraint(["confirmed_posting_id"], ["job_postings.id"], ondelete="RESTRICT", name=op.f("fk_job_import_candidates_confirmed_posting_id_job_postings")),
        sa.ForeignKeyConstraint(["confirmed_posting_id", "confirmed_snapshot_id"], ["job_snapshots.posting_id", "job_snapshots.id"], ondelete="RESTRICT", name="fk_job_import_candidates_confirmed_snapshot"),
    )


def downgrade() -> None:
    """候选或平台内容存在时拒绝降级，避免丢失来源和确认审计。"""
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM job_import_candidates) OR EXISTS (SELECT 1 FROM job_postings WHERE source <> 'MANUAL') THEN RAISE EXCEPTION 'platform import data exists; downgrade refused'; END IF; END $$")
    op.drop_table("job_import_candidates")
    op.drop_constraint(op.f("ck_job_postings_job_source"), "job_postings", type_="check")
    op.create_check_constraint("job_source", "job_postings", "source = 'MANUAL'")
