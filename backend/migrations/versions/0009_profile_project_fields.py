"""profile projects：成果列与所属工作经历关联

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-27 00:00:00.000000

项目经历补两项：

- `achievements`：成果，与工作经历同名同义。导入候选里的 `achievements` 从"并入说明"改为写入此列。
- `experience_id`：可选地关联到某段工作经历；个人项目留空。外键用 `RESTRICT`，删除被关联的经历
  由服务层拦成 409 并列出项目名——关联是用户建立的关系，不能静默解绑。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """升级到本修订。"""
    op.add_column(
        "profile_projects",
        sa.Column("achievements", sa.Text(), nullable=True, comment="成果描述，鼓励量化；与工作经历同名同义。"),
    )
    op.add_column(
        "profile_projects",
        sa.Column("experience_id", sa.UUID(), nullable=True, comment="可选：所属工作经历；个人项目为空。"),
    )
    op.create_index(op.f("ix_profile_projects_experience_id"), "profile_projects", ["experience_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_profile_projects_experience_id_profile_experiences"),
        "profile_projects",
        "profile_experiences",
        ["experience_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """回退到上一修订。"""
    op.drop_constraint(
        op.f("fk_profile_projects_experience_id_profile_experiences"),
        "profile_projects",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_profile_projects_experience_id"), table_name="profile_projects")
    op.drop_column("profile_projects", "experience_id")
    op.drop_column("profile_projects", "achievements")
