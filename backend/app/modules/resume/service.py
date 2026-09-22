"""Resume 领域的业务规则。

职责边界：

- 状态机集中在此：候选稿只能从 `DRAFT` 迁移到 `CONFIRMED` 或 `DISCARDED`，且迁移通过乐观锁
  条件更新完成，使"重复确认生成两份版本"在数据库层就不可能发生。
- 简历版本一旦创建就不可修改：任何调整都必须产生新版本，这是"历史投递可原样回看"的前提。
  因此本模块不提供任何修改或删除版本的入口。
- 事务由本层显式提交。确认候选稿时"新建版本 + 更新候选稿状态"必须在同一事务内，否则会出现
  "版本已生成但候选稿仍待确认"的不一致状态。
- 纯计算（证据去重、文档结构版本读取）保持同步函数：ADR 0002 明确"为了统一而到处加 async"
  会在事件循环里同步阻塞且更难测试。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ResourceNotFoundError, ValidationFailedError
from app.core.responses import ErrorDetail
from app.core.versioning import apply_versioned_update, collect_updates, table_of
from app.modules.profile.models import ProfileRevision

from . import repository as repo
from .enums import DraftStatus, ResumeStatus
from .models import Resume, ResumeDraft, ResumeVersion
from .schemas import (
    ResumeCreate,
    ResumeDraftConfirm,
    ResumeDraftCreate,
    ResumeDraftDiscard,
    ResumeDraftUpdate,
    ResumeUpdate,
    ResumeVersionCreate,
)


async def _require_resume(session: AsyncSession, resume_id: uuid.UUID) -> Resume:
    """读取简历方向，不存在则 404。

    参数:
        session: 当前会话。
        resume_id: 简历主键。

    返回:
        Resume: 简历方向。

    异常:
        ResourceNotFoundError: 记录不存在时抛出。
    """
    resume = await repo.get_by_id(session, Resume, resume_id)
    if resume is None:
        raise ResourceNotFoundError("请求的资源不存在。")
    return resume


async def _require_owned_draft(session: AsyncSession, resume_id: uuid.UUID, draft_id: uuid.UUID) -> ResumeDraft:
    """读取属于指定简历的候选稿。

    参数:
        session: 当前会话。
        resume_id: 简历主键。
        draft_id: 候选稿主键。

    返回:
        ResumeDraft: 候选稿。

    异常:
        ResourceNotFoundError: 候选稿不存在或不属于该简历时抛出。

    注意:
        不属于该简历时按"不存在"处理，避免通过错误信息探测其他简历的候选稿是否存在。
    """
    draft = await repo.get_by_id(session, ResumeDraft, draft_id)
    if draft is None or draft.resume_id != resume_id:
        raise ResourceNotFoundError("请求的资源不存在。")
    return draft


def _ensure_active(resume: Resume) -> None:
    """校验简历方向未归档。

    参数:
        resume: 简历方向。

    异常:
        ConflictError: 已归档时抛出 409。

    注意:
        归档的含义是"这一方向已停用"；继续为它生成版本或候选稿会让归档失去意义。
        确需继续维护时应先把它改回 ACTIVE，而不是让系统默认允许。
    """
    if resume.status is ResumeStatus.ARCHIVED:
        raise ConflictError("该简历方向已归档，不能新增版本或候选稿。")


async def _require_revision(session: AsyncSession, revision_id: uuid.UUID) -> ProfileRevision:
    """读取被引用的资料修订。

    参数:
        session: 当前会话。
        revision_id: 修订主键。

    返回:
        ProfileRevision: 修订实体；其 `snapshot_json` 是文档事实溯源的判定依据。

    异常:
        ValidationFailedError: 修订不存在时抛出 422，并指出出错字段。
    """
    revision = await repo.get_profile_revision(session, revision_id)
    if revision is None:
        raise ValidationFailedError(
            "引用的资料修订不存在。",
            details=[ErrorDetail(field="profile_revision_id", reason="请先为当前资料创建一份修订。")],
        )
    return revision


# 文档中存放带溯源内容的字段；顺序即报错时的呈现顺序。
_TEXT_BLOCK_KEYS: tuple[str, ...] = ("summary",)
_FACT_LIST_KEYS: tuple[str, ...] = ("experiences", "projects", "skills", "educations", "languages")

# 修订快照中"可被引用的事实"所在字段：档案本身 + 证据 + 五类事实。
_SNAPSHOT_OBJECT_KEY = "profile"
_SNAPSHOT_LIST_KEYS: tuple[str, ...] = ("evidences", *_FACT_LIST_KEYS)


def _as_mapping(value: object) -> Mapping[str, Any]:
    """把 JSON 数据中的值收窄为对象视图。

    参数:
        value: 任意 JSON 值。

    返回:
        Mapping[str, Any]: 对象视图；传入的不是对象时返回空映射。

    注意:
        直接在调用处写 `isinstance(value, Mapping)` 会让静态检查把值推断成
        `Mapping[Unknown, Unknown]`，之后每次取值都变成"类型部分未知"。
        统一在这里收窄一次，把无类型推断挡在校验逻辑之外。
    """
    return cast("Mapping[str, Any]", value) if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    """把 JSON 数据中的值收窄为数组视图。

    参数:
        value: 任意 JSON 值。

    返回:
        list[Any]: 数组视图；传入的不是数组时返回空列表。
    """
    return cast("list[Any]", value) if isinstance(value, list) else []


def _refs_of_item(path: str, item: Mapping[str, Any]) -> list[tuple[str, str]]:
    """取出单个条目上的溯源引用。

    参数:
        path: 该条目 `source_fact_id` 的字段路径。
        item: 条目数据。

    返回:
        list[tuple[str, str]]: 有引用时返回一项，否则返回空列表。

    注意:
        主键统一转成小写字符串再比较：数据库写入的是小写形式，而客户端可能提交大写十六进制，
        直接比较字符串会把等价的主键判成不同。
    """
    fact_id = item.get("source_fact_id")
    if fact_id is None:
        return []
    return [(path, str(fact_id).lower())]


def _collect_source_fact_refs(document: Mapping[str, Any]) -> list[tuple[str, str]]:
    """收集文档中全部 `source_fact_id` 及其字段路径。

    参数:
        document: 文档内容（`document_json` 形式的纯数据）。

    返回:
        list[tuple[str, str]]: (字段路径, 事实主键) 列表，路径形如 `skills.0.source_fact_id`。

    注意:
        按纯数据遍历而不是用 `ResumeDocument` 反序列化：候选稿可能由旧版结构写入，
        用当前模型解析会在校验之前先失败；这里的目的是"能读到什么就校验什么"。
    """
    refs: list[tuple[str, str]] = []
    for key in _TEXT_BLOCK_KEYS:
        block = _as_mapping(document.get(key))
        if block:
            refs.extend(_refs_of_item(f"{key}.source_fact_id", block))
    for key in _FACT_LIST_KEYS:
        for index, raw_item in enumerate(_as_list(document.get(key))):
            item = _as_mapping(raw_item)
            if item:
                refs.extend(_refs_of_item(f"{key}.{index}.source_fact_id", item))
    return refs


def _snapshot_fact_ids(snapshot: Mapping[str, Any]) -> set[str]:
    """提取修订快照中出现的全部主键。

    参数:
        snapshot: `profile_revisions.snapshot_json` 的内容。

    返回:
        set[str]: 小写字符串形式的主键集合。
    """
    ids: set[str] = set()
    profile_id = _as_mapping(snapshot.get(_SNAPSHOT_OBJECT_KEY)).get("id")
    if profile_id is not None:
        ids.add(str(profile_id).lower())
    for key in _SNAPSHOT_LIST_KEYS:
        for raw_entry in _as_list(snapshot.get(key)):
            entry_id = _as_mapping(raw_entry).get("id")
            if entry_id is not None:
                ids.add(str(entry_id).lower())
    return ids


async def _ensure_facts_traceable(revision: ProfileRevision, document: Mapping[str, Any]) -> None:
    """校验文档引用的事实确实存在于该修订中。

    参数:
        revision: 文档所指向的资料修订。
        document: 文档内容。

    异常:
        ValidationFailedError: 存在指向修订中不存在事实的引用时抛出 422，逐条给出字段路径。

    注意:
        判定依据是**该修订的快照**而不是"当前事实"：修订是时点快照，只有按它判定才能保证
        "这个版本当时依据的是什么"可复现；否则修订之后新增的事实会悄悄变成合法溯源。
        引用范围取快照中出现的任意主键（档案本身、证据、五类事实），而不按事实种类分别限制：
        校验要回答的是"这条内容能否追溯到该修订中的已记录内容"，快照本身就是当时的完整清单，
        按种类限制则会在新增事实类型时不断需要同步修改。
    """
    refs = _collect_source_fact_refs(document)
    if not refs:
        return
    known = _snapshot_fact_ids(revision.snapshot_json)
    missing = [(path, fact_id) for path, fact_id in refs if fact_id not in known]
    if not missing:
        return
    raise ValidationFailedError(
        "简历内容引用了资料修订中不存在的事实。",
        details=[
            ErrorDetail(field=path, reason=f"事实 {fact_id} 不在修订 {revision.revision_no} 中。")
            for path, fact_id in missing
        ],
    )


async def _ensure_evidences_usable(
    session: AsyncSession,
    evidence_ids: Sequence[uuid.UUID],
) -> list[uuid.UUID]:
    """校验证据存在且未归档，并返回去重后的主键。

    参数:
        session: 当前会话。
        evidence_ids: 客户端提交的证据主键。

    返回:
        list[uuid.UUID]: 去重且保持提交顺序的证据主键。

    异常:
        ValidationFailedError: 存在找不到或已归档的证据时抛出 422。

    注意:
        去重是必要的：关联表上有 `UNIQUE(resume_version_id, evidence_id)`，
        重复提交同一证据若不先合并，会把用户输入变成数据库层报错。
    """
    unique_ids = list(dict.fromkeys(evidence_ids))
    if not unique_ids:
        return []

    found = {evidence.id: evidence for evidence in await repo.list_evidences_by_ids(session, unique_ids)}
    missing = [evidence_id for evidence_id in unique_ids if evidence_id not in found]
    archived = [
        evidence_id
        for evidence_id in unique_ids
        if (evidence := found.get(evidence_id)) is not None and evidence.archived_at is not None
    ]

    details = (
        [
            ErrorDetail(field="evidence_ids", reason=f"以下证据不存在：{_format_ids(missing)}"),
        ]
        if missing
        else []
    )
    if archived:
        details.append(ErrorDetail(field="evidence_ids", reason=f"以下证据已归档：{_format_ids(archived)}"))
    if details:
        raise ValidationFailedError("关联的证据不可用。", details=details)
    return unique_ids


def _format_ids(ids: Sequence[uuid.UUID]) -> str:
    """把主键列表格式化为可读的错误信息片段。

    参数:
        ids: 主键列表。

    返回:
        str: 以顿号分隔的主键文本。
    """
    return "、".join(str(item) for item in ids)


def _document_schema_version(draft: ResumeDraft) -> int:
    """读取候选稿文档的结构版本。

    参数:
        draft: 候选稿。

    返回:
        int: 文档自身的结构版本号。

    异常:
        ValidationFailedError: 缺少可识别版本号时抛出。

    注意:
        这里只读取版本号而不重新用当前模型校验整份文档：候选稿创建时已经校验过，
        再次校验会让"模型后来演进"变成"旧候选稿无法确认"，而两份文档本身没有变。
    """
    raw = draft.document_json.get("schema_version")
    if not isinstance(raw, int) or raw <= 0:
        raise ValidationFailedError(
            "候选稿缺少可识别的文档结构版本。",
            details=[ErrorDetail(field="document", reason="document_json 缺少有效的 schema_version。")],
        )
    return raw


# --------------------------------------------------------------------------------------------
# 简历方向
# --------------------------------------------------------------------------------------------


async def list_resumes(session: AsyncSession, *, include_archived: bool) -> Sequence[Resume]:
    """列出简历方向。

    参数:
        session: 当前会话。
        include_archived: 是否包含已归档的简历方向。

    返回:
        Sequence[Resume]: 简历方向列表。
    """
    return await repo.list_resumes(session, include_archived=include_archived)


async def get_resume(session: AsyncSession, resume_id: uuid.UUID) -> Resume:
    """读取简历方向。

    参数:
        session: 当前会话。
        resume_id: 简历主键。

    返回:
        Resume: 简历方向。

    异常:
        ResourceNotFoundError: 记录不存在。
    """
    return await _require_resume(session, resume_id)


async def create_resume(session: AsyncSession, payload: ResumeCreate) -> Resume:
    """创建简历方向。

    参数:
        session: 当前会话。
        payload: 创建请求体。

    返回:
        Resume: 新建的简历方向。

    注意:
        不对简历名称做唯一约束：同一方向允许存在多份（例如中英文版本），
        强行唯一会迫使用户在名称里加后缀来绕过约束。
    """
    resume = Resume(name=payload.name, target_direction=payload.target_direction)
    await repo.add(session, resume)
    await session.commit()
    return resume


async def update_resume(session: AsyncSession, resume_id: uuid.UUID, payload: ResumeUpdate) -> Resume:
    """局部更新简历方向。

    参数:
        session: 当前会话。
        resume_id: 简历主键。
        payload: 局部更新请求体。

    返回:
        Resume: 更新后的简历方向。

    异常:
        ResourceNotFoundError: 记录不存在。
        ConflictError: 版本号已过期。
    """
    resume = await _require_resume(session, resume_id)
    await apply_versioned_update(session, resume, payload.version, collect_updates(payload))
    await session.commit()
    return resume


async def archive_resume(session: AsyncSession, resume_id: uuid.UUID) -> Resume:
    """归档简历方向。

    参数:
        session: 当前会话。
        resume_id: 简历主键。

    返回:
        Resume: 归档后的简历方向。

    异常:
        ResourceNotFoundError: 记录不存在。
        ConflictError: 已处于归档状态。

    注意:
        界面的"删除"在此实现为归档：版本会被历史投递引用，物理删除会让这些引用指向不存在的对象。
        DELETE 不带请求体，因此没有可比对的提交版本号，这里直接赋值并自增版本号，
        使后续 PATCH 的乐观锁仍然有效。
    """
    resume = await _require_resume(session, resume_id)
    if resume.status is ResumeStatus.ARCHIVED:
        raise ConflictError("该简历方向已归档。")
    resume.status = ResumeStatus.ARCHIVED
    resume.version += 1
    await session.flush()
    # `updated_at` 由数据库端 `onupdate=now()` 生成，flush 后该属性处于过期状态；
    # 不显式刷新就交给 Pydantic 序列化，会在同步上下文触发惰性加载并抛 MissingGreenlet。
    await session.refresh(resume)
    await session.commit()
    return resume


# --------------------------------------------------------------------------------------------
# 简历版本
# --------------------------------------------------------------------------------------------


async def list_versions(session: AsyncSession, resume_id: uuid.UUID, *, limit: int) -> Sequence[ResumeVersion]:
    """列出简历版本，最新在前。

    参数:
        session: 当前会话。
        resume_id: 简历主键。
        limit: 返回条数上限。

    返回:
        Sequence[ResumeVersion]: 版本列表。

    异常:
        ResourceNotFoundError: 简历不存在。
    """
    resume = await _require_resume(session, resume_id)
    return await repo.list_versions(session, resume.id, limit=limit)


async def get_version(session: AsyncSession, version_id: uuid.UUID) -> ResumeVersion:
    """读取简历版本。

    参数:
        session: 当前会话。
        version_id: 版本主键。

    返回:
        ResumeVersion: 版本。

    异常:
        ResourceNotFoundError: 记录不存在。
    """
    version = await repo.get_by_id(session, ResumeVersion, version_id)
    if version is None:
        raise ResourceNotFoundError("请求的资源不存在。")
    return version


async def version_evidence_ids(
    session: AsyncSession,
    version_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """批量读取版本的证据关联。

    参数:
        session: 当前会话。
        version_ids: 版本主键列表。

    返回:
        dict[uuid.UUID, list[uuid.UUID]]: 版本主键到证据主键列表的映射。
    """
    return await repo.list_version_ids_with_evidences(session, version_ids)


async def create_version(
    session: AsyncSession,
    resume_id: uuid.UUID,
    payload: ResumeVersionCreate,
) -> ResumeVersion:
    """为简历创建一个不可变版本。

    参数:
        session: 当前会话。
        resume_id: 简历主键。
        payload: 创建请求体。

    返回:
        ResumeVersion: 新建版本。

    异常:
        ResourceNotFoundError: 简历不存在。
        ConflictError: 简历已归档。
        ValidationFailedError: 资料修订或证据不可用，或文档引用了该修订中不存在的事实。
    """
    resume = await _require_resume(session, resume_id)
    _ensure_active(resume)
    revision = await _require_revision(session, payload.profile_revision_id)
    # `mode="json"` 让日期与 UUID 变成 JSON 可序列化形式；否则 JSONB 写入时会直接失败。
    document_json = payload.document.model_dump(mode="json")
    # 校验在写库之前：版本一经创建即不可变，"可溯源"必须成立在它落库的那一刻。
    await _ensure_facts_traceable(revision, document_json)
    evidence_ids = await _ensure_evidences_usable(session, payload.evidence_ids)

    version = ResumeVersion(
        resume_id=resume.id,
        version_no=await repo.next_version_no(session, resume.id),
        profile_revision_id=revision.id,
        document_json=document_json,
        render_schema_version=payload.document.schema_version,
        created_reason=payload.created_reason,
    )
    await repo.add(session, version)
    await repo.add_version_evidences(session, version.id, evidence_ids)
    await session.commit()
    return version


# --------------------------------------------------------------------------------------------
# 候选稿
# --------------------------------------------------------------------------------------------


async def list_drafts(
    session: AsyncSession,
    resume_id: uuid.UUID,
    *,
    status: DraftStatus | None,
    limit: int,
) -> Sequence[ResumeDraft]:
    """列出候选稿。

    参数:
        session: 当前会话。
        resume_id: 简历主键。
        status: 只返回该状态；为 None 时返回全部。
        limit: 返回条数上限。

    返回:
        Sequence[ResumeDraft]: 候选稿列表。

    异常:
        ResourceNotFoundError: 简历不存在。
    """
    resume = await _require_resume(session, resume_id)
    return await repo.list_drafts(session, resume.id, status=status, limit=limit)


async def get_draft(session: AsyncSession, resume_id: uuid.UUID, draft_id: uuid.UUID) -> ResumeDraft:
    """按主键读取候选稿。

    参数:
        session: 当前会话。
        resume_id: 简历主键。
        draft_id: 候选稿主键。

    返回:
        ResumeDraft: 候选稿。

    异常:
        ResourceNotFoundError: 简历不存在，或候选稿不存在/不属于该简历。

    注意:
        编辑与预览只需要这一份内容。让客户端拉取列表再自行筛选，会在候选稿数量超过列表上限时
        变成"这条记录明明存在却打不开"，而那个失败与权限、网络都无关，很难排查。
    """
    resume = await _require_resume(session, resume_id)
    return await _require_owned_draft(session, resume.id, draft_id)


async def create_draft(session: AsyncSession, resume_id: uuid.UUID, payload: ResumeDraftCreate) -> ResumeDraft:
    """创建候选稿。

    参数:
        session: 当前会话。
        resume_id: 简历主键。
        payload: 创建请求体。

    返回:
        ResumeDraft: 新候选稿，状态为 DRAFT。

    异常:
        ResourceNotFoundError: 简历不存在。
        ConflictError: 简历已归档。
        ValidationFailedError: 基线版本不存在或不属于该简历。

    注意:
        候选稿创建后不修改正式版本；只有确认才产生版本。因此这里允许 content 来自任何生成方，
        并记录 `generator_name` 以便区分人工与模型输出。
    """
    resume = await _require_resume(session, resume_id)
    _ensure_active(resume)

    if payload.base_resume_version_id is not None:
        base = await repo.get_by_id(session, ResumeVersion, payload.base_resume_version_id)
        if base is None or base.resume_id != resume.id:
            raise ValidationFailedError(
                "基线版本不存在或不属于该简历。",
                details=[ErrorDetail(field="base_resume_version_id", reason="请选择该简历已有版本的 id。")],
            )

    draft = ResumeDraft(
        resume_id=resume.id,
        base_resume_version_id=payload.base_resume_version_id,
        document_json=payload.document.model_dump(mode="json"),
        status=DraftStatus.DRAFT,
        generator_name=payload.generator_name,
        generator_version=payload.generator_version,
    )
    await repo.add(session, draft)
    await session.commit()
    return draft


def _ensure_draft_pending(draft: ResumeDraft) -> None:
    """校验候选稿仍待处理。

    参数:
        draft: 候选稿。

    异常:
        ConflictError: 已确认或已丢弃时抛出 409。

    注意:
        状态判断先于乐观锁版本判断：用户看到的是"这份候选稿已经处理过了"，
        而"版本号过期"会让人以为刷新后还能重试。
    """
    if draft.status is not DraftStatus.DRAFT:
        raise ConflictError(
            "该候选稿已处理，不能再次确认或丢弃。",
            details=[ErrorDetail(field="status", reason=f"当前状态为 {draft.status.value}。")],
        )


async def update_draft(
    session: AsyncSession,
    resume_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: ResumeDraftUpdate,
) -> ResumeDraft:
    """就地修改待确认的候选稿。

    参数:
        session: 当前会话。
        resume_id: 简历主键。
        draft_id: 候选稿主键。
        payload: 完整文档与乐观锁版本号。

    返回:
        ResumeDraft: 更新后的候选稿。

    异常:
        ResourceNotFoundError: 简历或候选稿不存在。
        ConflictError: 简历已归档、候选稿已处理，或版本号过期。

    注意:
        只允许改 `DRAFT` 状态的候选稿：确认或丢弃之后它就是一次历史决定，
        再允许修改会让"当初确认的到底是什么内容"无从回答。
        状态条件同时写进 `WHERE`（不只做读取时判断），使并发下"确认"与"编辑"不会同时成功——
        否则会出现"内容在确认之后又被改掉，但版本已经生成"的错位。
    """
    resume = await _require_resume(session, resume_id)
    _ensure_active(resume)
    draft = await _require_owned_draft(session, resume.id, draft_id)
    _ensure_draft_pending(draft)
    await apply_versioned_update(
        session,
        draft,
        payload.version,
        {"document_json": payload.document.model_dump(mode="json")},
        extra_conditions=[table_of(draft).c["status"] == DraftStatus.DRAFT],
    )
    await session.commit()
    return draft


async def confirm_draft(
    session: AsyncSession,
    resume_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: ResumeDraftConfirm,
) -> ResumeVersion:
    """确认候选稿并据此生成一个新版本。

    参数:
        session: 当前会话。
        resume_id: 简历主键。
        draft_id: 候选稿主键。
        payload: 确认请求体。

    返回:
        ResumeVersion: 新生成的版本。

    异常:
        ResourceNotFoundError: 简历或候选稿不存在。
        ConflictError: 候选稿已处理，或并发确认导致状态已被改变。
        ValidationFailedError: 资料修订或证据不可用，或文档引用了该修订中不存在的事实。

    注意:
        "新建版本"与"更新候选稿状态"在同一事务内完成，且状态条件写进 `WHERE`：
        并发重复确认时只有一个请求能命中条件更新，另一个请求因未命中而整体回滚，
        因此不会留下第二份版本、也不会耗尽候选稿。
    """
    resume = await _require_resume(session, resume_id)
    _ensure_active(resume)
    draft = await _require_owned_draft(session, resume.id, draft_id)
    _ensure_draft_pending(draft)
    revision = await _require_revision(session, payload.profile_revision_id)
    await _ensure_facts_traceable(revision, draft.document_json)
    evidence_ids = await _ensure_evidences_usable(session, payload.evidence_ids)

    version = ResumeVersion(
        resume_id=resume.id,
        version_no=await repo.next_version_no(session, resume.id),
        profile_revision_id=revision.id,
        document_json=draft.document_json,
        render_schema_version=_document_schema_version(draft),
        created_reason=payload.created_reason,
    )
    await repo.add(session, version)
    await repo.add_version_evidences(session, version.id, evidence_ids)
    await apply_versioned_update(
        session,
        draft,
        payload.version,
        {"status": DraftStatus.CONFIRMED, "confirmed_resume_version_id": version.id},
        extra_conditions=[table_of(draft).c["status"] == DraftStatus.DRAFT],
    )
    await session.commit()
    return version


async def discard_draft(
    session: AsyncSession,
    resume_id: uuid.UUID,
    draft_id: uuid.UUID,
    payload: ResumeDraftDiscard,
) -> ResumeDraft:
    """丢弃候选稿。

    参数:
        session: 当前会话。
        resume_id: 简历主键。
        draft_id: 候选稿主键。
        payload: 丢弃请求体。

    返回:
        ResumeDraft: 状态为 DISCARDED 的候选稿。

    异常:
        ResourceNotFoundError: 简历或候选稿不存在。
        ConflictError: 候选稿已处理，或并发操作导致状态已被改变。
    """
    resume = await _require_resume(session, resume_id)
    draft = await _require_owned_draft(session, resume.id, draft_id)
    _ensure_draft_pending(draft)
    await apply_versioned_update(
        session,
        draft,
        payload.version,
        {"status": DraftStatus.DISCARDED},
        extra_conditions=[table_of(draft).c["status"] == DraftStatus.DRAFT],
    )
    await session.commit()
    return draft
