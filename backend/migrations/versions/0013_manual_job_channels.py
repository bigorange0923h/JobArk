"""增加手工渠道与公司介绍；历史来源和业务内容不变。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加可空列，不猜测或回填旧记录的用户渠道。"""
    op.add_column("job_postings", sa.Column("channel_name", sa.String(80), nullable=True, comment="用户声明的渠道，不证明自动访问成功。"))
    op.add_column("companies", sa.Column("description", sa.Text(), nullable=True, comment="用户提供的公司介绍，不自动确认分类。"))


def downgrade() -> None:
    """仅无新增业务内容时移除列；非空内容须先明确处理，避免静默丢失。"""
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM companies WHERE description IS NOT NULL)
           OR EXISTS (SELECT 1 FROM job_postings WHERE channel_name IS NOT NULL) THEN
            RAISE EXCEPTION 'manual channel or company description exists; downgrade refused';
        END IF;
    END $$""")
    op.drop_column("companies", "description")
    op.drop_column("job_postings", "channel_name")
