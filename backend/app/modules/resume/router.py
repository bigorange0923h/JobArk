"""Resume 领域的 HTTP 接口。

约定：

- 所有响应都包裹在统一契约中（见 ADR 0001），失败由 `app/core/exception_handlers.py` 统一构造。
- 路由只做参数绑定与响应包装，业务规则全在 `service.py`；这里不出现 `try/except`。
- 批次内的资源（版本、候选稿）都挂在 `/resumes/{resume_id}` 之下，使归属关系体现在路径上；
  唯一的例外是 `GET /resume-versions/{version_id}`：投递记录只持有版本主键，
  从版本反查简历是它的真实使用方式，因此保留这个扁平入口。

主要错误映射（细节见 ADR 0001 的错误码表）：

- `RESOURCE_NOT_FOUND`：简历、版本或候选稿不存在（含不属于该简历的候选稿）。
- `CONFLICT`：版本号过期、简历已归档、候选稿已被处理。
- `VALIDATION_ERROR`：文档结构非法、资料修订不存在、证据不可用、基线版本不属于该简历。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.responses import ApiResponse, success

from . import service
from .enums import DraftStatus
from .models import ResumeVersion
from .schemas import (
    ResumeCreate,
    ResumeDraftConfirm,
    ResumeDraftCreate,
    ResumeDraftDiscard,
    ResumeDraftRead,
    ResumeDraftUpdate,
    ResumeRead,
    ResumeUpdate,
    ResumeVersionCreate,
    ResumeVersionRead,
)

router = APIRouter(tags=["resume"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _version_read(version: ResumeVersion, evidence_ids: Sequence[uuid.UUID]) -> ResumeVersionRead:
    """把版本实体与证据关联组装为响应体。

    参数:
        version: 版本实体。
        evidence_ids: 该版本关联的证据主键。

    返回:
        ResumeVersionRead: 响应体。

    注意:
        证据关联存放在独立表中，不在版本实体的属性上，因此无法直接 `model_validate`，
        必须显式组装。集中在此处可避免每个接口各写一遍字段映射。
    """
    return ResumeVersionRead(
        id=version.id,
        resume_id=version.resume_id,
        version_no=version.version_no,
        profile_revision_id=version.profile_revision_id,
        document_json=version.document_json,
        render_schema_version=version.render_schema_version,
        created_reason=version.created_reason,
        created_at=version.created_at,
        evidence_ids=list(evidence_ids),
    )


# --------------------------------------------------------------------------------------------
# 简历方向
# --------------------------------------------------------------------------------------------


@router.get(
    "/resumes",
    summary="列出简历方向",
    description="默认排除已归档的简历方向；`include_archived=true` 可一并返回。",
    response_model=ApiResponse[list[ResumeRead]],
)
async def list_resumes(
    session: SessionDep,
    include_archived: Annotated[bool, Query(description="是否包含已归档的简历方向。")] = False,
) -> ApiResponse[list[ResumeRead]]:
    """列出简历方向。

    参数:
        session: 请求级数据库会话。
        include_archived: 是否包含已归档的简历方向。

    返回:
        ApiResponse[list[ResumeRead]]: 简历方向列表。
    """
    resumes = await service.list_resumes(session, include_archived=include_archived)
    return success([ResumeRead.model_validate(resume) for resume in resumes])


@router.post(
    "/resumes",
    summary="创建简历方向",
    description="简历方向是可持续维护的表达单位，不是某次投递的附件；投递记录引用的是具体版本。",
    response_model=ApiResponse[ResumeRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_resume(session: SessionDep, payload: ResumeCreate) -> ApiResponse[ResumeRead]:
    """创建简历方向。

    参数:
        session: 请求级数据库会话。
        payload: 创建请求体。

    返回:
        ApiResponse[ResumeRead]: 新建的简历方向。
    """
    resume = await service.create_resume(session, payload)
    return success(ResumeRead.model_validate(resume))


@router.get(
    "/resumes/{resume_id}",
    summary="读取简历方向",
    description="返回简历方向的名称、目标方向与状态。版本与候选稿通过各自的列表接口获取。",
    response_model=ApiResponse[ResumeRead],
)
async def get_resume(session: SessionDep, resume_id: uuid.UUID) -> ApiResponse[ResumeRead]:
    """读取简历方向。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。

    返回:
        ApiResponse[ResumeRead]: 简历方向。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
    """
    resume = await service.get_resume(session, resume_id)
    return success(ResumeRead.model_validate(resume))


@router.patch(
    "/resumes/{resume_id}",
    summary="更新简历方向",
    description="局部更新名称、目标方向或状态；必须提交当前 version，版本过期返回 409。",
    response_model=ApiResponse[ResumeRead],
)
async def update_resume(
    session: SessionDep,
    resume_id: uuid.UUID,
    payload: ResumeUpdate,
) -> ApiResponse[ResumeRead]:
    """局部更新简历方向。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。
        payload: 待更新字段与乐观锁版本号。

    返回:
        ApiResponse[ResumeRead]: 更新后的简历方向。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
        CONFLICT: 版本号已过期。
    """
    resume = await service.update_resume(session, resume_id, payload)
    return success(ResumeRead.model_validate(resume))


@router.delete(
    "/resumes/{resume_id}",
    summary="归档简历方向",
    description="把简历方向置为 ARCHIVED，不物理删除：历史版本会被投递记录引用，删除会让这些引用失效。",
    response_model=ApiResponse[ResumeRead],
)
async def archive_resume(session: SessionDep, resume_id: uuid.UUID) -> ApiResponse[ResumeRead]:
    """归档简历方向。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。

    返回:
        ApiResponse[ResumeRead]: 归档后的简历方向。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
        CONFLICT: 该简历已归档。
    """
    resume = await service.archive_resume(session, resume_id)
    return success(ResumeRead.model_validate(resume))


# --------------------------------------------------------------------------------------------
# 简历版本
# --------------------------------------------------------------------------------------------


@router.get(
    "/resumes/{resume_id}/versions",
    summary="列出简历版本",
    description="版本不可变且按版本号倒序返回；历史投递引用的版本始终可以原样查看。",
    response_model=ApiResponse[list[ResumeVersionRead]],
)
async def list_versions(
    session: SessionDep,
    resume_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=200, description="返回条数上限。")] = 50,
) -> ApiResponse[list[ResumeVersionRead]]:
    """列出简历版本。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。
        limit: 返回条数上限。

    返回:
        ApiResponse[list[ResumeVersionRead]]: 版本列表。

    异常:
        RESOURCE_NOT_FOUND: 简历不存在。
    """
    versions = await service.list_versions(session, resume_id, limit=limit)
    evidences = await service.version_evidence_ids(session, [version.id for version in versions])
    return success([_version_read(version, evidences.get(version.id, [])) for version in versions])


@router.post(
    "/resumes/{resume_id}/versions",
    summary="创建简历版本",
    description="创建一个不可变版本，必须指向一份已存在的资料修订。版本号与服务端渲染结构版本由服务端确定。",
    response_model=ApiResponse[ResumeVersionRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_version(
    session: SessionDep,
    resume_id: uuid.UUID,
    payload: ResumeVersionCreate,
) -> ApiResponse[ResumeVersionRead]:
    """创建简历版本。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。
        payload: 版本内容。

    返回:
        ApiResponse[ResumeVersionRead]: 新建版本。

    异常:
        RESOURCE_NOT_FOUND: 简历不存在。
        CONFLICT: 简历已归档。
        VALIDATION_ERROR: 资料修订不存在或证据不可用。
    """
    version = await service.create_version(session, resume_id, payload)
    # 回读实际写入的关联而不是回显请求体：重复提交的证据会被合并，回显会与库中真实关联不一致。
    evidences = await service.version_evidence_ids(session, [version.id])
    return success(_version_read(version, evidences.get(version.id, [])))


@router.get(
    "/resume-versions/{version_id}",
    summary="读取简历版本",
    description="按版本主键直接读取。投递记录只持有版本主键，因此需要这个不经过简历的入口。",
    response_model=ApiResponse[ResumeVersionRead],
)
async def get_version(session: SessionDep, version_id: uuid.UUID) -> ApiResponse[ResumeVersionRead]:
    """读取简历版本。

    参数:
        session: 请求级数据库会话。
        version_id: 版本主键。

    返回:
        ApiResponse[ResumeVersionRead]: 版本内容。

    异常:
        RESOURCE_NOT_FOUND: 记录不存在。
    """
    version = await service.get_version(session, version_id)
    evidences = await service.version_evidence_ids(session, [version.id])
    return success(_version_read(version, evidences.get(version.id, [])))


# --------------------------------------------------------------------------------------------
# 候选稿
# --------------------------------------------------------------------------------------------


@router.get(
    "/resumes/{resume_id}/drafts",
    summary="列出候选稿",
    description="默认返回全部状态；`status` 可只取待确认的候选稿。候选稿不是正式版本。",
    response_model=ApiResponse[list[ResumeDraftRead]],
)
async def list_drafts(
    session: SessionDep,
    resume_id: uuid.UUID,
    status_filter: Annotated[
        DraftStatus | None,
        Query(alias="status", description="只返回该状态的候选稿。"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="返回条数上限。")] = 50,
) -> ApiResponse[list[ResumeDraftRead]]:
    """列出候选稿。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。
        status_filter: 只返回该状态的候选稿。
        limit: 返回条数上限。

    返回:
        ApiResponse[list[ResumeDraftRead]]: 候选稿列表。

    异常:
        RESOURCE_NOT_FOUND: 简历不存在。
    """
    drafts = await service.list_drafts(session, resume_id, status=status_filter, limit=limit)
    return success([ResumeDraftRead.model_validate(draft) for draft in drafts])


@router.post(
    "/resumes/{resume_id}/drafts",
    summary="创建候选稿",
    description="创建一份候选简历稿（V1 手工构造，后续由 AI 流程写入同一张表）。确认前不影响任何正式版本。",
    response_model=ApiResponse[ResumeDraftRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_draft(
    session: SessionDep,
    resume_id: uuid.UUID,
    payload: ResumeDraftCreate,
) -> ApiResponse[ResumeDraftRead]:
    """创建候选稿。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。
        payload: 候选内容与生成元数据。

    返回:
        ApiResponse[ResumeDraftRead]: 新候选稿。

    异常:
        RESOURCE_NOT_FOUND: 简历不存在。
        CONFLICT: 简历已归档。
        VALIDATION_ERROR: 基线版本不存在或不属于该简历。
    """
    draft = await service.create_draft(session, resume_id, payload)
    return success(ResumeDraftRead.model_validate(draft))


@router.get(
    "/resumes/{resume_id}/drafts/{draft_id}",
    summary="读取候选稿",
    description="按主键读取一份候选稿；编辑与预览都以它为唯一数据来源。",
    response_model=ApiResponse[ResumeDraftRead],
)
async def get_draft(
    session: SessionDep,
    resume_id: uuid.UUID,
    draft_id: uuid.UUID,
) -> ApiResponse[ResumeDraftRead]:
    """读取候选稿。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。
        draft_id: 候选稿主键。

    返回:
        ApiResponse[ResumeDraftRead]: 候选稿内容。

    异常:
        RESOURCE_NOT_FOUND: 简历或候选稿不存在（含不属于该简历的候选稿）。
    """
    draft = await service.get_draft(session, resume_id, draft_id)
    return success(ResumeDraftRead.model_validate(draft))


@router.patch(
    "/resumes/{resume_id}/drafts/{draft_id}",
    summary="修改候选稿",
    description=(
        "就地修改待确认的候选稿内容，必须提交完整文档与当前版本号。"
        "已确认或已丢弃的候选稿返回 409；编辑候选稿不会产生正式版本，正式版本只能由确认产生。"
    ),
    response_model=ApiResponse[ResumeDraftRead],
)
async def update_draft(
    session: SessionDep,
    resume_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: ResumeDraftUpdate,
) -> ApiResponse[ResumeDraftRead]:
    """修改候选稿。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。
        draft_id: 候选稿主键。
        payload: 替换后的完整文档与乐观锁版本号。

    返回:
        ApiResponse[ResumeDraftRead]: 更新后的候选稿。

    异常:
        RESOURCE_NOT_FOUND: 简历或候选稿不存在（含不属于该简历的候选稿）。
        CONFLICT: 简历已归档、候选稿已处理，或版本号已过期。
        VALIDATION_ERROR: 文档结构非法。
    """
    draft = await service.update_draft(session, resume_id, draft_id, payload)
    return success(ResumeDraftRead.model_validate(draft))


@router.post(
    "/resumes/{resume_id}/drafts/{draft_id}/confirm",
    summary="确认候选稿",
    description="确认候选内容并新建一个不可变版本；已有版本永不被覆盖，同一候选稿只能确认一次。",
    response_model=ApiResponse[ResumeVersionRead],
    status_code=status.HTTP_201_CREATED,
)
async def confirm_draft(
    session: SessionDep,
    resume_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: ResumeDraftConfirm,
) -> ApiResponse[ResumeVersionRead]:
    """确认候选稿。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。
        draft_id: 候选稿主键。
        payload: 确认请求体。

    返回:
        ApiResponse[ResumeVersionRead]: 新生成的版本。

    异常:
        RESOURCE_NOT_FOUND: 简历或候选稿不存在。
        CONFLICT: 候选稿已处理，或版本号已过期。
        VALIDATION_ERROR: 资料修订不存在或证据不可用。
    """
    version = await service.confirm_draft(session, resume_id, draft_id, payload)
    evidences = await service.version_evidence_ids(session, [version.id])
    return success(_version_read(version, evidences.get(version.id, [])))


@router.post(
    "/resumes/{resume_id}/drafts/{draft_id}/discard",
    summary="丢弃候选稿",
    description="把候选稿标记为 DISCARDED；不生成版本，已确认的候选稿不能再丢弃。",
    response_model=ApiResponse[ResumeDraftRead],
)
async def discard_draft(
    session: SessionDep,
    resume_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: ResumeDraftDiscard,
) -> ApiResponse[ResumeDraftRead]:
    """丢弃候选稿。

    参数:
        session: 请求级数据库会话。
        resume_id: 简历主键。
        draft_id: 候选稿主键。
        payload: 丢弃请求体。

    返回:
        ApiResponse[ResumeDraftRead]: 状态为 DISCARDED 的候选稿。

    异常:
        RESOURCE_NOT_FOUND: 简历或候选稿不存在。
        CONFLICT: 候选稿已处理，或版本号已过期。
    """
    draft = await service.discard_draft(session, resume_id, draft_id, payload)
    return success(ResumeDraftRead.model_validate(draft))
