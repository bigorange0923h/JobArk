"""Job 领域独立不可变公司公开报告；不预留多租户或通用任务平台。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建最小报告表，来源结构固定在不可变 JSON 中。"""
    op.create_table(
        "company_research_reports",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="记录创建时间（UTC）。",
        ),
        sa.Column(
            "opportunity_id", sa.UUID(), sa.ForeignKey("job_opportunities.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("identity_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, comment="独立完成、部分来源、待确认或安全失败状态。"),
        sa.Column("report_json", JSONB(), nullable=False, comment="固定实体、来源摘录和分维度结论。"),
    )
    for name in ("opportunity_id", "company_id", "identity_fingerprint"):
        op.create_index(f"ix_company_research_reports_{name}", "company_research_reports", [name])


def downgrade() -> None:
    """有报告时拒绝回退，不静默删除公开资料与审计依据。"""
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM company_research_reports) THEN
            RAISE EXCEPTION 'company research reports exist; downgrade refused';
        END IF;
    END $$""")
    op.drop_table("company_research_reports")
