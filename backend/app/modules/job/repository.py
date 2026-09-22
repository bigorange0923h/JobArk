"""Job 领域查询与持久化构造；事务与业务规则在服务层。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.errors import ConflictError

from .models import Company, JobOpportunity, JobPosting, JobSnapshot


async def add[ModelT: Base](session: AsyncSession, entity: ModelT) -> ModelT:
    """加入实体并 flush，以便同一事务的下一步使用数据库生成字段。"""
    session.add(entity)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise ConflictError("该页面或 JD 内容已存在，请打开已有职位。") from error
        raise
    return entity


async def get_opportunity(session: AsyncSession, opportunity_id: uuid.UUID) -> JobOpportunity | None:
    """按主键读取职位机会。"""
    return await session.get(JobOpportunity, opportunity_id)


async def get_company(session: AsyncSession, company_id: uuid.UUID) -> Company | None:
    """按主键读取公司。"""
    return await session.get(Company, company_id)


async def list_postings(session: AsyncSession, opportunity_id: uuid.UUID) -> Sequence[JobPosting]:
    """读取机会的页面，最早发现的页面在前。"""
    result = await session.scalars(
        select(JobPosting)
        .where(JobPosting.opportunity_id == opportunity_id)
        .order_by(JobPosting.first_seen_at, JobPosting.id)
    )
    return result.all()


async def get_posting(session: AsyncSession, posting_id: uuid.UUID) -> JobPosting | None:
    """按主键读取职位页面。"""
    return await session.get(JobPosting, posting_id)


async def latest_snapshot(session: AsyncSession, posting_id: uuid.UUID) -> JobSnapshot | None:
    """读取指定页面最新的内容快照。"""
    return await session.scalar(
        select(JobSnapshot)
        .where(JobSnapshot.posting_id == posting_id)
        .order_by(JobSnapshot.captured_at.desc(), JobSnapshot.created_at.desc())
        .limit(1)
    )


async def get_snapshot_by_hash(session: AsyncSession, posting_id: uuid.UUID, content_hash: str) -> JobSnapshot | None:
    """检查相同内容是否已经作为该页面的快照保存。"""
    return await session.scalar(
        select(JobSnapshot).where(JobSnapshot.posting_id == posting_id, JobSnapshot.content_hash == content_hash)
    )


async def list_opportunities(session: AsyncSession) -> Sequence[JobOpportunity]:
    """列出职位机会，最近更新的排在前。"""
    result = await session.scalars(
        select(JobOpportunity).order_by(JobOpportunity.updated_at.desc(), JobOpportunity.id.desc())
    )
    return result.all()


async def list_snapshots(session: AsyncSession, opportunity_id: uuid.UUID) -> Sequence[JobSnapshot]:
    """按时间倒序读取机会的全部快照，保留历史原文供申请选择。"""
    return (
        await session.scalars(
            select(JobSnapshot)
            .join(JobPosting)
            .where(JobPosting.opportunity_id == opportunity_id)
            .order_by(JobSnapshot.captured_at.desc(), JobSnapshot.id)
        )
    ).all()
