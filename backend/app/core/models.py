"""模型通用列约定。

`docs/data-model.md` 1.2 规定：所有表使用 `id UUID` 主键与 `created_at TIMESTAMPTZ`；
可编辑实体额外有 `updated_at` 与用于 API 乐观锁的 `version`。
把这些列集中为 mixin，避免各领域重复声明时出现偏差（例如漏掉 `version` 或时区类型不一致）。

不可变实体（修订、快照、匹配结果、事件）**不应**继承 `EditableMixin`：它们不提供内容更新接口，
多出 `version` 会暗示可以更新。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column


class UuidPrimaryKeyMixin:
    """UUID 主键。

    主键由应用生成（`uuid4`）而不是依赖数据库默认值：服务层在写入前就需要 id
    （例如构造修订快照引用），若由数据库生成则必须额外 flush 才能拿到。
    """

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    """创建时间，按 UTC 存储。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="记录创建时间（UTC）。",
    )


class EditableMixin(CreatedAtMixin):
    """可编辑实体的通用列：创建时间、更新时间与乐观锁版本号。"""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="最后更新时间（UTC），由 ORM 在更新时刷新。",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
        default=1,
        comment="乐观锁版本号；每次更新自增，接口提交旧值即返回 409。",
    )
