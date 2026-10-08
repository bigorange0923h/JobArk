"""增加可空学历维度和独立策略字段；不推断或回填真实个人资料。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """只增加结构和空默认值，不修改旧 degree 和求职策略。"""
    op.add_column("profile_educations", sa.Column("degree_level", sa.String(32), nullable=True))
    op.add_column("profile_educations", sa.Column("study_mode", sa.String(32), nullable=True))
    op.create_check_constraint(
        "degree_level_allowed",
        "profile_educations",
        "degree_level IS NULL OR degree_level IN ('HIGH_SCHOOL','ASSOCIATE','BACHELOR','MASTER','DOCTOR','OTHER')",
    )
    op.create_check_constraint(
        "study_mode_allowed",
        "profile_educations",
        "study_mode IS NULL OR study_mode IN ('FULL_TIME','PART_TIME','OTHER')",
    )
    op.add_column(
        "profile_preferences",
        sa.Column("role_keywords", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("profile_preferences", sa.Column("acceptable_salary_min", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "acceptable_salary_nonnegative",
        "profile_preferences",
        "acceptable_salary_min IS NULL OR acceptable_salary_min >= 0",
    )


def downgrade() -> None:
    """新字段有用户内容时拒绝回退，避免静默丢失。"""
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM profile_educations WHERE degree_level IS NOT NULL OR study_mode IS NOT NULL)
            OR EXISTS (SELECT 1 FROM profile_preferences WHERE role_keywords <> '[]'::jsonb OR acceptable_salary_min IS NOT NULL) THEN
            RAISE EXCEPTION 'refinement inputs exist; downgrade refused';
        END IF;
    END $$""")
    op.drop_constraint("acceptable_salary_nonnegative", "profile_preferences", type_="check")
    op.drop_column("profile_preferences", "acceptable_salary_min")
    op.drop_column("profile_preferences", "role_keywords")
    op.drop_constraint("study_mode_allowed", "profile_educations", type_="check")
    op.drop_constraint("degree_level_allowed", "profile_educations", type_="check")
    op.drop_column("profile_educations", "study_mode")
    op.drop_column("profile_educations", "degree_level")
