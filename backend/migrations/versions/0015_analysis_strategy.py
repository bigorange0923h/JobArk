"""增补显式策略与解析引用；旧偏好不启用硬限制。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加必要输入列与物理解析外键；报告 JSON 保存固定策略。"""
    op.add_column(
        "job_opportunities",
        sa.Column(
            "work_terms",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="用户明确确认的薪资口径与工作方式。",
        ),
    )
    for name, default in (("target_roles", "[]"), ("hard_limits", "{}"), ("priority_rules", "[]")):
        op.add_column(
            "profile_preferences",
            sa.Column(name, JSONB(), nullable=False, server_default=sa.text(f"'{default}'::jsonb")),
        )
    op.add_column("match_results", sa.Column("parse_result_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_match_results_parse_result_id_job_parse_results",
        "match_results",
        "job_parse_results",
        ["parse_result_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_match_results_parse_result_id", "match_results", ["parse_result_id"])


def downgrade() -> None:
    """有新策略或新报告引用时拒绝静默丢失。"""
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM profile_preferences WHERE target_roles <> '[]'::jsonb
            OR priority_rules <> '[]'::jsonb OR hard_limits NOT IN ('{}'::jsonb,
            jsonb_build_object('location', false, 'employment_type', false, 'remote', false, 'salary', false, 'salary_basis', NULL)))
            OR EXISTS (SELECT 1 FROM match_results WHERE parse_result_id IS NOT NULL)
            OR EXISTS (SELECT 1 FROM job_opportunities WHERE work_terms NOT IN ('{}'::jsonb, jsonb_build_object('remote_mode', NULL, 'salary', NULL))) THEN
            RAISE EXCEPTION 'analysis inputs exist; downgrade refused';
        END IF;
    END $$""")
    op.drop_index("ix_match_results_parse_result_id", table_name="match_results")
    op.drop_constraint("fk_match_results_parse_result_id_job_parse_results", "match_results", type_="foreignkey")
    op.drop_column("match_results", "parse_result_id")
    for name in ("priority_rules", "hard_limits", "target_roles"):
        op.drop_column("profile_preferences", name)
    op.drop_column("job_opportunities", "work_terms")
