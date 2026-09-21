"""可编辑实体的乐观锁更新。

`docs/data-model.md` 1.2 规定可编辑实体带 `version` 列，接口提交旧值时返回 409。
比较与写入必须合并为一条 `UPDATE ... WHERE id = ? AND version = ?`：先读后写之间存在竞态窗口，
两个并发请求都可能各自通过"读取时的版本检查"，而条件更新由数据库保证只有一个写入成功。

抽出到 core 而不是各领域各写一份：版本检查一旦在不同模块里出现细微差异（例如某处忘记自增、
或把比较与写入拆成两条语句），就会变成难以复现的数据覆盖问题。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Protocol, cast

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Table
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped

from .errors import ConflictError
from .responses import ErrorDetail


class EditableEntity(Protocol):
    """乐观锁更新所需的最小实体接口。

    只声明更新逻辑真正使用的成员，从而对"可编辑实体"做结构化约束，
    而不是把所有模型都退化成 `Any`。

    注意:
        成员类型声明为 `Mapped[...]` 而不是 `UUID`/`int`：本协议约束的是 ORM 映射实体，
        而 SQLAlchemy 在类上声明的是描述符。若写成普通类型，类型检查会认为所有模型都不满足协议
        （`Mapped[UUID]` 与 `UUID` 不兼容），协议就永远无法被真实类型满足，等于没有约束。
    """

    id: Mapped[uuid.UUID]
    version: Mapped[int]


def table_of(entity: EditableEntity) -> Table:
    """取实体对应的表对象。

    参数:
        entity: 任一可编辑实体实例。

    返回:
        Table: 该实体映射的数据库表。

    注意:
        ORM 在类上注入 `__table__`，但类型存根未声明该属性，因此这里做一次显式转换。
        使用表对象而不是拼接 SQL 文本，可以让条件更新保持参数化。
    """
    # Ruff 的 B009 建议直接写 type(entity).__table__，但 Protocol 未声明该属性，直接访问无法通过
    # Pyright 检查；这里保留 getattr 并做定向豁免。
    return cast(Table, getattr(type(entity), "__table__"))  # noqa: B009


def collect_updates(payload: BaseModel) -> dict[str, Any]:
    """从局部更新请求体中取出待写入字段。

    参数:
        payload: 任一 `*Update` 请求体。

    返回:
        dict[str, Any]: 仅包含客户端显式提交的字段（显式传 null 表示清空），且不含乐观锁版本号。
    """
    return payload.model_dump(exclude_unset=True, exclude={"version"})


async def apply_versioned_update(
    session: AsyncSession,
    entity: EditableEntity,
    submitted_version: int,
    updates: dict[str, Any],
    *,
    extra_conditions: Sequence[ColumnElement[bool]] = (),
) -> None:
    """按提交的版本号条件更新实体。

    参数:
        session: 当前会话。
        entity: 已加载的实体。
        submitted_version: 客户端提交的版本号。
        updates: 待写入字段。
        extra_conditions: 附加的更新前置条件，例如"仅当状态仍为 DRAFT 时才允许确认"。
            把状态判断一起放进 `WHERE` 而不是先读后写，使"重复确认生成两份版本"这类问题
            在数据库层就不可能发生。

    异常:
        ConflictError: 版本号不匹配，或条件更新未命中任何行时抛出 409。

    注意:
        写入后刷新实体，使返回值反映增量后的版本号；`onupdate=now()` 生成的 `updated_at`
        在 flush 后处于过期状态，不刷新就交给 Pydantic 序列化会在同步上下文触发惰性加载。
    """
    if entity.version != submitted_version:
        raise ConflictError(
            "记录已被更新，请刷新后重试。",
            details=[
                ErrorDetail(
                    field="version",
                    reason=f"当前版本为 {entity.version}，提交的是 {submitted_version}。",
                )
            ],
        )

    table = table_of(entity)
    statement = (
        table.update()
        .where(
            table.c["id"] == entity.id,
            table.c["version"] == submitted_version,
            *extra_conditions,
        )
        .values(**updates, version=submitted_version + 1)
        .returning(table.c["version"])
    )
    if (await session.execute(statement)).scalar_one_or_none() is None:
        raise ConflictError("记录已被其他操作更新，请刷新后重试。")
    await session.refresh(entity)
