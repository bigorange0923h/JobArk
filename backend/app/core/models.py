"""模型通用列约定。

`docs/data-model.md` 1.2 规定：所有表使用 `id UUID` 主键与 `created_at TIMESTAMPTZ`；
可编辑实体额外有 `updated_at` 与用于 API 乐观锁的 `version`。
把这些列集中为 mixin，避免各领域重复声明时出现偏差（例如漏掉 `version` 或时区类型不一致）。

不可变实体（修订、快照、匹配结果、事件）**不应**继承 `EditableMixin`：它们不提供内容更新接口，
多出 `version` 会暗示可以更新。
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Integer, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SAEnum


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


def enum_values(enum_cls: type[StrEnum]) -> list[str]:
    """返回枚举的持久化取值集合。

    参数:
        enum_cls: 目标枚举类。

    返回:
        list[str]: 各成员的值；作为 CHECK 约束的取值集合。

    注意:
        SQLAlchemy 默认持久化成员的**名字**而不是值。这里显式指定按值存储，
        使数据库中出现的就是 `UNVERIFIED` 这类可读取值，而不是 Python 成员名。
    """
    return [member.value for member in enum_cls]


def enum_column_type(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """构造 VARCHAR + CHECK 形式的枚举列类型。

    参数:
        enum_cls: 枚举类。
        name: 约束名后缀，最终形如 `ck_<table>_<name>`（由 Base 的命名约定拼接）。

    返回:
        SAEnum: 非原生枚举列类型。

    注意:
        刻意不用 PostgreSQL 原生枚举：原生枚举新增取值需要 `ALTER TYPE`，且不能在事务块内完成，
        而 Alembic 默认在事务中执行迁移；用 CHECK 则把取值变更变成一次普通的约束替换。
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=32,
        name=name,
        values_callable=enum_values,
    )
