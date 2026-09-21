"""baseline：迁移基线，不含业务表

Revision ID: 0001
Revises:
Create Date: 2026-09-21

阶段 0 的验收要求是"空数据库可重复迁移"，因此首个修订只登记基线、不创建任何表：
它验证的是迁移链路（upgrade/downgrade 可反复执行、版本表可正确维护），
而不是引入未论证的表结构。业务表从阶段 1 起由各领域模型经 autogenerate 产生。
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """基线修订：无结构变更。"""


def downgrade() -> None:
    """回退基线修订：无结构变更。"""
