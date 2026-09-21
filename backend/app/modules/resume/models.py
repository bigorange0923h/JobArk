"""Resume 领域的数据模型，对应 `docs/data-model.md` 第 4 节。

建模约定与理由：

- `resumes` 是可持续维护的"简历方向"，**不携带指向 Profile 或 ProfileRevision 的外键**：
  V1 只有一份主档案，而"这一版简历基于哪份资料修订"记录在 `resume_versions.profile_revision_id`。
  简历方向本身若绑定某个修订，会与"长期维护、之后从新修订继续生成版本"的语义冲突。
- `resume_versions` 不继承 `EditableMixin`：它是不可变记录，没有"更新"语义，只被新增与被引用。
  它是 Application 唯一允许引用的对象，因此历史投递在任何后续编辑后仍可原样查看。
- `resume_version_evidences` 保留版本与真实证据的**显式**关联，而不是从 `document_json` 反推：
  文档结构会随渲染模板演进，证据关联必须在数据层稳定可查。
- `resume_drafts` 继承 `EditableMixin`：候选稿会经历状态迁移（确认/丢弃），确认操作依赖乐观锁
  条件更新完成，使"重复确认生成两份版本"在数据库层就不可能发生。
- 本模块不声明 ORM 关系：聚合读取通过 repository 的显式查询完成，避免隐式惰性加载
  在异步会话下抛 MissingGreenlet。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import CreatedAtMixin, EditableMixin, UuidPrimaryKeyMixin, enum_column_type

from .enums import DraftStatus, ResumeStatus

# 生成器标识的默认值：V1 尚未接入 LLM，候选稿由用户手工构造；接入后由生成方写入真实模型标识。
DEFAULT_GENERATOR_NAME = "MANUAL"


class Resume(UuidPrimaryKeyMixin, EditableMixin, Base):
    """一份可持续维护的简历方向。

    它是"表达版本"的组织单位，不是某次投递的附件：投递记录引用的是 `ResumeVersion`。
    """

    __tablename__ = "resumes"

    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="简历方向名称，例如 Java 后端。")
    target_direction: Mapped[str | None] = mapped_column(
        String(200),
        comment="目标方向，用于区分同一档案下的多份简历，例如 后端 / AI 应用。",
    )
    status: Mapped[ResumeStatus] = mapped_column(
        enum_column_type(ResumeStatus, "status"),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )


class ResumeVersion(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """不可变的简历版本。

    版本一旦创建就不再修改，这是"历史投递可原样回看"的实现前提：任何调整都产生新版本。
    """

    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint("resume_id", "version_no", name="uq_resume_versions_resume_id_version_no"),
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint("render_schema_version > 0", name="render_schema_version_positive"),
    )

    resume_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="同一简历内自增，从 1 开始。")
    profile_revision_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="生成该版本时使用的资料修订；保证简历可复现，而不是指向会继续变化的当前事实。",
    )
    document_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="结构化的简历文档；条目可携带 source_fact_id 指回 Profile 事实，用于校验未编造内容。",
    )
    render_schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="document_json 的结构版本，决定用哪套渲染与解析规则解释它。",
    )
    created_reason: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="创建原因，例如 首次创建 / 针对某职位定制 / 确认候选稿。",
    )


class ResumeVersionEvidence(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """简历版本与真实证据的显式关联。

    版本与证据的关系随版本一起确定，之后不再调整：变更关联应当产生新版本，
    否则"某个历史版本用了哪些证据"会随编辑而漂移。
    """

    __tablename__ = "resume_version_evidences"
    __table_args__ = (
        UniqueConstraint(
            "resume_version_id",
            "evidence_id",
            name="uq_resume_version_evidences_resume_version_id_evidence_id",
        ),
    )

    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile_evidences.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class ResumeDraft(UuidPrimaryKeyMixin, EditableMixin, Base):
    """AI 或人工生成的候选简历稿。

    候选稿不构成正式版本：只有确认后才会新建 `ResumeVersion`。确认前的内容不会出现在任何
    正式版本中，因此"AI 优化的结果"不可能悄悄覆盖用户已有的简历。
    """

    __tablename__ = "resume_drafts"
    __table_args__ = (
        # 状态与"已确认版本"必须同时成立或同时不成立：避免出现状态为已确认却没有产出，
        # 或产出已存在却仍停留在待确认状态这两种自相矛盾的记录。
        CheckConstraint(
            "(status = 'CONFIRMED') = (confirmed_resume_version_id IS NOT NULL)",
            name="confirmed_status_matches_version",
        ),
        # 失败必须留痕：否则"生成失败"会表现为一条内容看似可用、实则来源不明的候选稿。
        CheckConstraint("status <> 'FAILED' OR failure_code IS NOT NULL", name="failed_requires_code"),
        UniqueConstraint("confirmed_resume_version_id", name="uq_resume_drafts_confirmed_resume_version_id"),
    )

    resume_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    base_resume_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="RESTRICT"),
        comment="作为改写基线的版本；为空表示这是一份从零生成的候选稿。",
    )
    document_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="候选内容；确认前不进入任何正式版本。",
    )
    status: Mapped[DraftStatus] = mapped_column(
        enum_column_type(DraftStatus, "status"),
        nullable=False,
        server_default=text("'DRAFT'"),
    )
    confirmed_resume_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="RESTRICT"),
        comment="确认后产出的版本；唯一约束保证一个版本只由一次确认产生。",
    )
    generator_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=text(f"'{DEFAULT_GENERATOR_NAME}'"),
        comment="生成方标识；手工构造为 MANUAL，接入模型后写入模型名。",
    )
    generator_version: Mapped[str | None] = mapped_column(
        String(64),
        comment="生成方版本，用于区分同一生成方的不同输出。",
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), comment="失败时的安全错误码；不保存上游原始错误文本。")
    failure_message: Mapped[str | None] = mapped_column(Text, comment="面向用户的失败说明，不得包含堆栈或密钥。")
