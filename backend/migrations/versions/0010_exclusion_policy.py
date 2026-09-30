"""求职策略：结构化规则、已确认输入、评估及单职位例外。

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增策略结构；旧 exclusions 与行业文本不作推断迁移。"""
    op.add_column("companies", sa.Column("nature_code", sa.String(40), nullable=True, comment="用户确认的公司性质代码。"))
    op.add_column("companies", sa.Column("industry_code", sa.String(80), nullable=True, comment="用户确认的两级行业代码。"))
    op.add_column("job_opportunities", sa.Column("outsourcing_arrangement", sa.String(32), nullable=True, comment="用户确认的岗位安排。"))
    op.create_table(
        "exclusion_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("singleton_key", sa.String(16), nullable=False, server_default="default", unique=True),
        sa.Column("rules", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.CheckConstraint("singleton_key = 'default'", name=op.f("ck_exclusion_policies_singleton_default")),
    )
    for table in ("exclusion_evaluations", "exclusion_exceptions"):
        columns = [
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("opportunity_id", UUID(as_uuid=True), sa.ForeignKey("job_opportunities.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("snapshot_id", UUID(as_uuid=True), sa.ForeignKey("job_snapshots.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("policy_version", sa.Integer(), nullable=False),
            sa.Column("company_version", sa.Integer(), nullable=False),
            sa.Column("opportunity_version", sa.Integer(), nullable=False),
        ]
        if table == "exclusion_evaluations":
            columns += [sa.Column("verdict", sa.String(16), nullable=False), sa.Column("reasons", JSONB(), nullable=False)]
        else:
            columns += [sa.Column("reason", sa.String(1000), nullable=False), sa.Column("confirmed", sa.Boolean(), nullable=False)]
        op.create_table(table, *columns)
        op.create_index(f"ix_{table}_opportunity_id", table, ["opportunity_id"])


def downgrade() -> None:
    """回退新结构，不触碰旧自由文本。"""
    for table in ("exclusion_exceptions", "exclusion_evaluations"):
        op.drop_index(f"ix_{table}_opportunity_id", table_name=table)
        op.drop_table(table)
    op.drop_table("exclusion_policies")
    op.drop_column("job_opportunities", "outsourcing_arrangement")
    op.drop_column("companies", "industry_code")
    op.drop_column("companies", "nature_code")
