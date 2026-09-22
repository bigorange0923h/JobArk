"""Job 领域服务：手工录入与不可变 JD 快照。"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ResourceNotFoundError
from app.core.versioning import apply_versioned_update

from . import repository
from .enums import JobSource, PostingStatus, SnapshotParseStatus
from .models import Company, JobOpportunity, JobPosting, JobSnapshot
from .schemas import (
    CompanyRead,
    JobListItem,
    JobManualCreate,
    JobOpportunityRead,
    JobOpportunityUpdate,
    JobPostingRead,
    JobSnapshotCreate,
    JobSnapshotRead,
)


def normalize_company_name(name: str) -> str:
    """压缩空白并转小写，仅用于辅助检索，绝不作为自动合并依据。"""
    return re.sub(r"\s+", " ", name.strip()).casefold()


def content_hash(raw_jd: str) -> str:
    """计算原始 JD 的稳定 SHA-256；快照不规范化正文，忠实保留用户输入。"""
    return hashlib.sha256(raw_jd.encode("utf-8")).hexdigest()


async def create_manual_job(session: AsyncSession, payload: JobManualCreate) -> JobOpportunityRead:
    """原子创建公司、机会、手工页面与首份未解析 JD 快照。"""
    company = await repository.add(
        session,
        Company(
            name=payload.company.name.strip(),
            name_normalized=normalize_company_name(payload.company.name),
            website_url=str(payload.company.website_url) if payload.company.website_url else None,
            industry=payload.company.industry,
            location=payload.company.location,
        ),
    )
    opportunity = await repository.add(
        session,
        JobOpportunity(
            company_id=company.id,
            title=payload.title.strip(),
            location=payload.location,
            employment_type=payload.employment_type,
            notes=payload.notes,
        ),
    )
    posting = await repository.add(
        session,
        JobPosting(
            opportunity_id=opportunity.id,
            source=JobSource.MANUAL,
            canonical_url=str(payload.canonical_url) if payload.canonical_url else None,
            page_status=PostingStatus.ACTIVE,
        ),
    )
    snapshot = await repository.add(
        session,
        JobSnapshot(
            posting_id=posting.id,
            content_hash=content_hash(payload.raw_jd),
            raw_jd=payload.raw_jd,
            parse_status=SnapshotParseStatus.NOT_REQUESTED,
        ),
    )
    await session.commit()
    return _read_opportunity(opportunity, company, [posting], snapshot)


async def require_opportunity(session: AsyncSession, opportunity_id: uuid.UUID) -> JobOpportunity:
    """读取职位机会，不存在时抛出统一 404。"""
    opportunity = await repository.get_opportunity(session, opportunity_id)
    if opportunity is None:
        raise ResourceNotFoundError("职位机会不存在。")
    return opportunity


async def get_opportunity_detail(session: AsyncSession, opportunity_id: uuid.UUID) -> JobOpportunityRead:
    """读取职位聚合，并以所有页面中最新的 JD 为当前快照。"""
    opportunity = await require_opportunity(session, opportunity_id)
    company = await repository.get_company(session, opportunity.company_id)
    if company is None:
        raise ResourceNotFoundError("职位关联的公司不存在。")
    postings = await repository.list_postings(session, opportunity.id)
    snapshots = [
        snapshot for posting in postings if (snapshot := await repository.latest_snapshot(session, posting.id))
    ]
    latest = max(snapshots, key=lambda item: (item.captured_at, item.created_at), default=None)
    return _read_opportunity(opportunity, company, postings, latest)


async def list_jobs(session: AsyncSession) -> list[JobListItem]:
    """列出职位机会及其最新 JD 时间，避免列表接口传输全文。"""
    items: list[JobListItem] = []
    for opportunity in await repository.list_opportunities(session):
        company = await repository.get_company(session, opportunity.company_id)
        if company is None:
            raise ResourceNotFoundError("职位关联的公司不存在。")
        snapshots = [
            snapshot
            for posting in await repository.list_postings(session, opportunity.id)
            if (snapshot := await repository.latest_snapshot(session, posting.id))
        ]
        latest = max(snapshots, key=lambda item: (item.captured_at, item.created_at), default=None)
        items.append(
            JobListItem(
                id=opportunity.id,
                created_at=opportunity.created_at,
                updated_at=opportunity.updated_at,
                version=opportunity.version,
                company_name=company.name,
                title=opportunity.title,
                location=opportunity.location,
                employment_type=opportunity.employment_type,
                status=opportunity.status,
                latest_snapshot_id=latest.id if latest else None,
                latest_captured_at=latest.captured_at if latest else None,
            )
        )
    return items


async def update_opportunity(
    session: AsyncSession, opportunity_id: uuid.UUID, payload: JobOpportunityUpdate
) -> JobOpportunityRead:
    """使用乐观锁更新可编辑职位字段。"""
    opportunity = await require_opportunity(session, opportunity_id)
    updates = payload.model_dump(exclude={"version"}, exclude_unset=True)
    if "title" in updates:
        updates["title"] = str(updates["title"]).strip()
    await apply_versioned_update(session, opportunity, payload.version, updates)
    await session.commit()
    return await get_opportunity_detail(session, opportunity.id)


async def create_snapshot(
    session: AsyncSession, opportunity_id: uuid.UUID, posting_id: uuid.UUID, payload: JobSnapshotCreate
) -> JobSnapshot:
    """为属于该机会的页面创建新的、未解析的 JD 快照。"""
    await require_opportunity(session, opportunity_id)
    posting = await repository.get_posting(session, posting_id)
    if posting is None or posting.opportunity_id != opportunity_id:
        raise ResourceNotFoundError("职位页面不存在。")
    digest = content_hash(payload.raw_jd)
    if await repository.get_snapshot_by_hash(session, posting.id, digest):
        raise ConflictError("该职位页面已保存内容相同的 JD 快照。")
    snapshot = await repository.add(
        session,
        JobSnapshot(
            posting_id=posting.id,
            content_hash=digest,
            raw_jd=payload.raw_jd,
            parse_status=SnapshotParseStatus.NOT_REQUESTED,
        ),
    )
    await session.commit()
    return snapshot


def _read_opportunity(
    opportunity: JobOpportunity, company: Company, postings: Sequence[JobPosting], latest_snapshot: JobSnapshot | None
) -> JobOpportunityRead:
    """把 ORM 聚合显式转换为响应模型，避免异步惰性加载。"""
    return JobOpportunityRead(
        id=opportunity.id,
        created_at=opportunity.created_at,
        updated_at=opportunity.updated_at,
        version=opportunity.version,
        company=CompanyRead.model_validate(company),
        title=opportunity.title,
        location=opportunity.location,
        employment_type=opportunity.employment_type,
        status=opportunity.status,
        notes=opportunity.notes,
        postings=[JobPostingRead.model_validate(posting) for posting in postings],
        latest_snapshot=JobSnapshotRead.model_validate(latest_snapshot) if latest_snapshot else None,
    )
