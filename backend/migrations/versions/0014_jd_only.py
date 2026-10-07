"""允许只保存 JD；拒绝以伪造公司满足历史非空约束。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """仅放宽机会字段，公司名称约束及所有历史引用不变。"""
    op.alter_column("job_opportunities", "company_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column(
        "job_opportunities",
        "title",
        existing_type=sa.String(200),
        nullable=True,
        comment="职位标题；缺失不造占位事实。",
    )


def downgrade() -> None:
    """存在缺失元数据时拒绝回退，不删除机会或创建假公司。"""
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM job_opportunities WHERE company_id IS NULL OR title IS NULL) THEN
            RAISE EXCEPTION 'JD-only opportunities exist; downgrade refused';
        END IF;
    END $$""")
    op.alter_column("job_opportunities", "title", existing_type=sa.String(200), nullable=False, comment="职位标题。")
    op.alter_column("job_opportunities", "company_id", existing_type=sa.UUID(), nullable=False)
