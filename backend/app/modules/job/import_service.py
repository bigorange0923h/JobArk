"""平台内容候选与确认事务；不执行平台访问，不自动改写已有机会元数据。"""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.automation.adapters.job_pages import extract_job, identify_posting
from app.core.errors import ConflictError, ResourceNotFoundError, ValidationFailedError
from app.core.versioning import apply_versioned_update

from . import repository, service
from .import_schemas import ImportConfirm, ImportConfirmation, ImportFields, ImportPreview, ImportRead
from .models import Company, JobImportCandidate, JobOpportunity, JobPosting, JobSnapshot


def read_candidate(entity: JobImportCandidate) -> ImportRead:
    """从保存的原候选和审计声明构造安全响应，不回读原始 HTML。"""
    return ImportRead(
        id=entity.id,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        version=entity.version,
        source=entity.source,
        external_id=entity.external_id,
        canonical_url=entity.canonical_url,
        status="CONFIRMED" if entity.status == "CONFIRMED" else "PENDING",
        expires_at=entity.expires_at,
        extractor_version=entity.extractor_version,
        fields=ImportFields.model_validate(entity.candidate_json["fields"]),
        warnings=entity.candidate_json["warnings"],
        target_posting_id=entity.target_posting_id,
        observed_posting_version=entity.observed_posting_version,
        confirmed_posting_id=entity.confirmed_posting_id,
        confirmed_snapshot_id=entity.confirmed_snapshot_id,
        reviewed_fields=ImportFields.model_validate(entity.reviewed_json) if entity.reviewed_json else None,
    )


async def get_candidate(session: AsyncSession, candidate_id: UUID) -> JobImportCandidate:
    """按 ID 读取候选；不存在返回 404，无外部副作用。"""
    entity = await session.get(JobImportCandidate, candidate_id)
    if entity is None:
        raise ResourceNotFoundError("导入候选不存在。")
    return entity


async def preview(session: AsyncSession, payload: ImportPreview) -> ImportRead:
    """本地提取并冻结候选，只写候选表，不创建正式职位。"""
    identity = identify_posting(payload.url)
    extracted = extract_job(payload.content, payload.mode, identity)
    try:
        fields = ImportFields(
            company_name=extracted.company_name,
            title=extracted.title,
            location=extracted.location,
            raw_jd=extracted.raw_jd,
        )
    except ValidationError as error:
        raise ValidationFailedError("页面字段过长或缺少正文，请改用单个职位正文并人工补全。") from error
    posting = await session.scalar(
        select(JobPosting).where(
            JobPosting.source == identity.source,
            JobPosting.external_id == identity.external_id,
        )
    )
    warnings = list(extracted.warnings)
    # 原始提取字段仍保存，用于解释人工内容与页面来源的区别；已有机会不以外部内容覆盖元数据。
    extracted_fields = fields.model_dump(mode="json")
    if posting is not None:
        opportunity = await service.require_opportunity(session, posting.opportunity_id)
        company = await repository.get_company(session, opportunity.company_id)
        if company is None:
            raise ResourceNotFoundError("职位关联的公司不存在。")
        fields = fields.model_copy(
            update={
                "company_name": company.name,
                "title": opportunity.title,
                "location": opportunity.location,
            }
        )
        warnings.append("这是已有平台页面；本次只更新 JD，不覆盖公司、标题、地点或已确认分类。")
    entity = JobImportCandidate(
        source=identity.source,
        external_id=identity.external_id,
        canonical_url=identity.canonical_url,
        input_hash=hashlib.sha256(payload.content.encode("utf-8")).hexdigest(),
        extractor_version=extracted.extractor_version,
        candidate_json={
            "fields": fields.model_dump(mode="json"),
            "extracted_fields": extracted_fields,
            "warnings": warnings,
        },
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        status="PENDING",
        target_posting_id=posting.id if posting else None,
        observed_posting_version=posting.version if posting else None,
    )
    session.add(entity)
    await session.commit()
    return read_candidate(entity)


async def confirm(session: AsyncSession, candidate_id: UUID, payload: ImportConfirm) -> ImportConfirmation:
    """有界等待后原子确认；锁等待超时回滚并返回可重试的安全冲突。"""
    try:
        await session.execute(text("SET LOCAL lock_timeout = '5s'"))
        await session.execute(text("SET LOCAL statement_timeout = '15s'"))
        return await _confirm(session, candidate_id, payload)
    except DBAPIError as error:
        await session.rollback()
        if getattr(error.orig, "sqlstate", None) in {"55P03", "57014"}:
            raise ConflictError("职位正在被其他操作处理，请稍后重试；本次未写入。") from error
        raise


async def _confirm(session: AsyncSession, candidate_id: UUID, payload: ImportConfirm) -> ImportConfirmation:
    """在事务内串行校验候选与来源身份，只允许一次正式写入并冻结产物引用。"""
    if not payload.confirm:
        raise ValidationFailedError("请明确确认将核对后的内容写入本地职位。")
    entity = await session.scalar(
        select(JobImportCandidate)
        .where(
            JobImportCandidate.id == candidate_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if entity is None:
        raise ResourceNotFoundError("导入候选不存在。")
    reviewed = payload.fields.model_dump(mode="json")
    if entity.status == "CONFIRMED":
        if entity.reviewed_json != reviewed or payload.version != entity.version - 1:
            raise ConflictError("此候选已确认，不能用不同内容或版本再次确认。")
        posting = await session.get(JobPosting, entity.confirmed_posting_id)
        if posting is None:
            raise ResourceNotFoundError("已确认的职位页面不存在。")
        if entity.confirmed_snapshot_id is None:
            raise ResourceNotFoundError("已确认的快照不存在。")
        return ImportConfirmation(
            opportunity_id=posting.opportunity_id,
            posting_id=posting.id,
            snapshot_id=entity.confirmed_snapshot_id,
        )
    if entity.version != payload.version or entity.expires_at <= datetime.now(UTC):
        raise ConflictError("候选已过期或版本变化，请重新预览并核对。")
    # 同一来源首次创建也必须串行：只锁已有页面不能阻止两个首次确认同时创建公司/机会。
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {
            "identity": f"job-import:{entity.source.value}:{entity.external_id}",
        },
    )
    posting = await session.scalar(
        select(JobPosting)
        .where(
            JobPosting.source == entity.source,
            JobPosting.external_id == entity.external_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (posting.id if posting else None) != entity.target_posting_id:
        raise ConflictError("平台页面已在其他操作中创建或变化，请重新预览。")
    # 锁等待可能跨过有效期，必须在实际写入前再次检查，不能沿用等待前的结论。
    if entity.expires_at <= datetime.now(UTC):
        raise ConflictError("候选已过期，请重新预览并核对。")
    if posting is not None:
        if posting.version != entity.observed_posting_version:
            raise ConflictError("此页面的 JD 已更新，请重新预览，避免覆盖新内容。")
        expected = ImportFields.model_validate(entity.candidate_json["fields"])
        if (payload.fields.company_name, payload.fields.title, payload.fields.location) != (
            expected.company_name.strip(),
            expected.title.strip(),
            (expected.location.strip() or None) if expected.location is not None else None,
        ):
            raise ValidationFailedError("更新已有页面只允许修改 JD；公司与职位信息请在职位编辑页面修改。")
        opportunity_id = posting.opportunity_id
    else:
        company = await repository.add(
            session,
            Company(
                name=payload.fields.company_name,
                name_normalized=service.normalize_company_name(payload.fields.company_name),
            ),
        )
        opportunity = await repository.add(
            session,
            JobOpportunity(
                company_id=company.id,
                title=payload.fields.title,
                location=payload.fields.location,
            ),
        )
        opportunity_id = opportunity.id
        posting = await repository.add(
            session,
            JobPosting(
                opportunity_id=opportunity.id,
                source=entity.source,
                external_id=entity.external_id,
                canonical_url=entity.canonical_url,
            ),
        )
    snapshot = await repository.get_snapshot_by_hash(session, posting.id, service.content_hash(payload.fields.raw_jd))
    if snapshot is None:
        snapshot = await repository.add(
            session,
            JobSnapshot(
                posting_id=posting.id,
                raw_jd=payload.fields.raw_jd,
                content_hash=service.content_hash(payload.fields.raw_jd),
            ),
        )
    await apply_versioned_update(
        session,
        posting,
        posting.version,
        {
            "current_snapshot_id": snapshot.id,
            "last_seen_at": datetime.now(UTC),
        },
    )
    await apply_versioned_update(
        session,
        entity,
        payload.version,
        {
            "status": "CONFIRMED",
            "reviewed_json": reviewed,
            "confirmed_posting_id": posting.id,
            "confirmed_snapshot_id": snapshot.id,
        },
    )
    await session.commit()
    return ImportConfirmation(opportunity_id=opportunity_id, posting_id=posting.id, snapshot_id=snapshot.id)
