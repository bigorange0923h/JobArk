"""Profile 领域的数据模型，对应 `docs/data-model.md` 第 3 节。

建模约定与理由：

- 主键、创建时间与乐观锁列来自 `app.core.models` 的 mixin，避免各表重复声明时出现偏差。
- 枚举列使用 `native_enum=False`（VARCHAR + CHECK）而不是 PostgreSQL 原生枚举：原生枚举新增取值
  需要 `ALTER TYPE`，且不能在事务块内完成，而 Alembic 默认在事务中执行迁移；用 CHECK 则把取值
  变更变成一次普通的约束替换。
- 需要检索、排序、比较的字段一律用显式列；只有技术栈、公开链接、目标地点这类不参与比较的
  小型列表才使用 JSONB。
- JSONB 列表由服务层**整体赋值**而不是原地修改：SQLAlchemy 默认不追踪容器内部变更。
- `profile_revisions` 不继承 `EditableMixin`：它是不可变记录，不存在"更新"语义。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import CreatedAtMixin, EditableMixin, UuidPrimaryKeyMixin, enum_column_type

from .enums import ClaimStatus, EvidenceSourceType, RemotePreference, SkillProficiency, VerificationStatus

# 技能名的规范化：小写、去除首尾空白、把连续空白折叠为单个空格，用于同一档案内的唯一约束。
_SKILL_NAME_NORMALIZED_LENGTH = 100


class PersonalProfile(UuidPrimaryKeyMixin, EditableMixin, Base):
    """个人档案根实体。

    V1 是单人本地工具：`singleton_key` 固定为 `default` 并由唯一约束保证只有一份主档案。
    将来引入多用户时应新增迁移加 `user_id`，而不是现在预留字段。
    """

    __tablename__ = "personal_profiles"
    __table_args__ = (
        UniqueConstraint("singleton_key", name="uq_personal_profiles_singleton_key"),
        CheckConstraint("singleton_key = 'default'", name="singleton_key_fixed"),
    )

    singleton_key: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'default'"),
        comment="固定为 default；唯一约束保证 V1 只有一份主档案。",
    )
    full_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="姓名。")
    headline: Mapped[str | None] = mapped_column(String(200), comment="一句话头衔，例如 Backend Engineer。")
    summary: Mapped[str | None] = mapped_column(Text, comment="个人简介。")
    email: Mapped[str | None] = mapped_column(
        String(320),
        comment="联系方式；仅存于本地库，日志与 AI 提示词不得无条件输出。",
    )
    phone: Mapped[str | None] = mapped_column(
        String(50),
        comment="联系方式；仅存于本地库，日志与 AI 提示词不得无条件输出。",
    )
    city: Mapped[str | None] = mapped_column(String(100), comment="所在城市。")
    links: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="公开链接列表，元素形如 {label, url}；不参与比较，因此使用 JSONB。",
    )

    evidences: Mapped[list[ProfileEvidence]] = relationship(
        back_populates="profile",
        lazy="selectin",
        order_by="ProfileEvidence.created_at",
    )
    skills: Mapped[list[ProfileSkill]] = relationship(back_populates="profile", lazy="selectin")
    experiences: Mapped[list[ProfileExperience]] = relationship(back_populates="profile", lazy="selectin")
    projects: Mapped[list[ProfileProject]] = relationship(back_populates="profile", lazy="selectin")
    educations: Mapped[list[ProfileEducation]] = relationship(back_populates="profile", lazy="selectin")
    languages: Mapped[list[ProfileLanguage]] = relationship(back_populates="profile", lazy="selectin")
    preference: Mapped[ProfilePreference | None] = relationship(back_populates="profile", lazy="selectin")


class ProfileEvidence(UuidPrimaryKeyMixin, EditableMixin, Base):
    """真实信息来源。

    同一份证据可被多条事实复用（各事实表持有 `source_evidence_id` 外键）。
    界面上的"删除"执行归档（写入 `archived_at`）而不是物理删除：已被事实引用的证据一旦消失，
    "结论可追溯到证据"这一要求就失效了。
    """

    __tablename__ = "profile_evidences"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personal_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[EvidenceSourceType] = mapped_column(
        enum_column_type(EvidenceSourceType, "source_type"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="证据标题，例如证书名称。")
    content: Mapped[str | None] = mapped_column(Text, comment="证据内容或说明。")
    source_url: Mapped[str | None] = mapped_column(String(2048), comment="可核验的外部链接。")
    source_hash: Mapped[str | None] = mapped_column(
        String(128),
        comment="来源内容哈希，用于识别同一份证据的重复导入。",
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_column_type(VerificationStatus, "verification_status"),
        nullable=False,
        server_default=text("'UNVERIFIED'"),
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="归档时间；非空表示该证据已从界面移除但保留引用完整性。",
    )

    profile: Mapped[PersonalProfile] = relationship(back_populates="evidences", lazy="raise")


class ProfileSkill(UuidPrimaryKeyMixin, EditableMixin, Base):
    """技能事实。

    `claim_status` 与 `source_evidence_id` 由数据库约束联动：标记为 `VERIFIED` 时必须挂证据，
    因此无法仅改一个字符串就把无凭据的陈述伪装成已验证事实。
    """

    __tablename__ = "profile_skills"
    __table_args__ = (
        UniqueConstraint("profile_id", "name_normalized", name="uq_profile_skills_profile_id_name_normalized"),
        CheckConstraint(
            "claim_status <> 'VERIFIED' OR source_evidence_id IS NOT NULL",
            name="verified_requires_evidence",
        ),
        CheckConstraint("years_of_experience IS NULL OR years_of_experience >= 0", name="years_non_negative"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personal_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="技能原名，保留用户书写。")
    name_normalized: Mapped[str] = mapped_column(
        String(_SKILL_NAME_NORMALIZED_LENGTH),
        nullable=False,
        comment="规范化技能名（小写、折叠空白），用于同一档案内的唯一约束。",
    )
    category: Mapped[str | None] = mapped_column(String(64), comment="技能分类，例如语言、框架、工具。")
    proficiency: Mapped[SkillProficiency | None] = mapped_column(enum_column_type(SkillProficiency, "proficiency"))
    years_of_experience: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), comment="使用年限，可含小数。")
    source_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile_evidences.id", ondelete="RESTRICT"),
        comment="支撑该技能的来源证据。",
    )
    claim_status: Mapped[ClaimStatus] = mapped_column(
        enum_column_type(ClaimStatus, "claim_status"),
        nullable=False,
        server_default=text("'UNVERIFIED'"),
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)

    profile: Mapped[PersonalProfile] = relationship(back_populates="skills", lazy="raise")


class ProfileExperience(UuidPrimaryKeyMixin, EditableMixin, Base):
    """工作经历。"""

    __tablename__ = "profile_experiences"
    __table_args__ = (CheckConstraint("end_date IS NULL OR end_date >= start_date", name="end_after_start"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personal_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="职位名称。")
    location: Mapped[str | None] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, comment="为空表示当前仍在职。")
    responsibilities: Mapped[str | None] = mapped_column(Text, comment="职责描述。")
    achievements: Mapped[str | None] = mapped_column(Text, comment="成果描述，鼓励量化。")
    source_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile_evidences.id", ondelete="RESTRICT"),
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)

    profile: Mapped[PersonalProfile] = relationship(back_populates="experiences", lazy="raise")


class ProfileProject(UuidPrimaryKeyMixin, EditableMixin, Base):
    """项目经历。

    工作项目与个人项目都记录在此，不强制绑定到某段工作经历：个人项目同样可以成为匹配证据。
    """

    __tablename__ = "profile_projects"
    __table_args__ = (
        CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR end_date >= start_date",
            name="end_after_start",
        ),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personal_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str | None] = mapped_column(String(100), comment="本人角色。")
    description: Mapped[str | None] = mapped_column(Text)
    tech_stack: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="技术栈列表；V1 无需跨用户统计，因此用 JSONB 而非关联表。",
    )
    url: Mapped[str | None] = mapped_column(String(2048))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    source_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile_evidences.id", ondelete="RESTRICT"),
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)

    profile: Mapped[PersonalProfile] = relationship(back_populates="projects", lazy="raise")


class ProfileEducation(UuidPrimaryKeyMixin, EditableMixin, Base):
    """教育经历。"""

    __tablename__ = "profile_educations"
    __table_args__ = (
        CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR end_date >= start_date",
            name="end_after_start",
        ),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personal_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    school: Mapped[str] = mapped_column(String(200), nullable=False)
    major: Mapped[str | None] = mapped_column(String(200))
    degree: Mapped[str | None] = mapped_column(String(64), comment="学位或学历层次。")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    source_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile_evidences.id", ondelete="RESTRICT"),
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)

    profile: Mapped[PersonalProfile] = relationship(back_populates="educations", lazy="raise")


class ProfileLanguage(UuidPrimaryKeyMixin, EditableMixin, Base):
    """语言能力。"""

    __tablename__ = "profile_languages"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personal_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str | None] = mapped_column(String(64), comment="水平描述，例如 CET-6、雅思 7.0。")
    note: Mapped[str | None] = mapped_column(Text)
    source_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile_evidences.id", ondelete="RESTRICT"),
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)

    profile: Mapped[PersonalProfile] = relationship(back_populates="languages", lazy="raise")


class ProfilePreference(UuidPrimaryKeyMixin, EditableMixin, Base):
    """求职偏好。

    偏好是**可变规则**，不是履历事实，因此不挂证据、不参与 `claim_status` 判定，
    每个档案只保留一行（`profile_id` 唯一）。
    """

    __tablename__ = "profile_preferences"
    __table_args__ = (
        UniqueConstraint("profile_id", name="uq_profile_preferences_profile_id"),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_max >= salary_min",
            name="salary_range_ordered",
        ),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personal_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_locations: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    job_types: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="职位类型，例如 FULL_TIME、CONTRACT。",
    )
    salary_min: Mapped[int | None] = mapped_column(Integer, comment="期望薪资下限，按月计。")
    salary_max: Mapped[int | None] = mapped_column(Integer, comment="期望薪资上限，按月计。")
    salary_currency: Mapped[str | None] = mapped_column(String(3), comment="ISO 4217 币种代码。")
    remote_preference: Mapped[RemotePreference | None] = mapped_column(
        enum_column_type(RemotePreference, "remote_preference"),
    )
    exclusions: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="排除条件，例如不接受的行业或公司。",
    )

    profile: Mapped[PersonalProfile] = relationship(back_populates="preference", lazy="raise")


class ProfileRevision(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """不可变的资料修订快照。

    匹配与简历需要可复现的输入，因此这两类流程必须引用修订而不是会继续变化的当前事实。
    修订只在创建 ResumeVersion、发起匹配或用户确认重要资料变更时创建，
    而不是每次编辑都创建——否则修订表会被输入框的中间状态淹没。
    """

    __tablename__ = "profile_revisions"
    __table_args__ = (
        UniqueConstraint("profile_id", "revision_no", name="uq_profile_revisions_profile_id_revision_no"),
        CheckConstraint("revision_no > 0", name="revision_no_positive"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personal_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="同一档案内自增，从 1 开始。")
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="当时的事实内容与来源证据 ID；匹配与简历只能引用它，不能直接读当前事实表。",
    )
    reason: Mapped[str] = mapped_column(String(200), nullable=False, comment="创建原因，例如 生成投递简历。")
