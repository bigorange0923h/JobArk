"""Profile 领域的请求与响应模型。

命名与语义约定：

- `*Create` 只用于创建，必填字段在模型层声明；`*Update` 用于局部更新，除 `version` 外全部可选，
  服务层用 `exclude_unset=True` 只更新显式提交的字段（显式传 `null` 表示清空该字段）。
- `*Update` 必须携带 `version`：它与数据库中的乐观锁列比对，不一致返回 409，避免覆盖他人改动。
- 数据库里的 CHECK 约束只能保证"写不进去"，无法给出可理解的错误；所有可能被用户输入触发的约束
  在此重复校验一次，以便返回 422 与字段级原因，而不是把 `IntegrityError` 变成 500。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ClaimStatus, EvidenceSourceType, RemotePreference, SkillProficiency, VerificationStatus


class ORMModel(BaseModel):
    """可从 ORM 实例构造的响应模型基类。"""

    model_config = ConfigDict(from_attributes=True)


class EditableRead(ORMModel):
    """可编辑实体的公共响应字段。"""

    id: UUID = Field(description="记录主键。")
    created_at: datetime = Field(description="创建时间（UTC）。")
    updated_at: datetime = Field(description="最后更新时间（UTC）。")
    version: int = Field(description="乐观锁版本号；局部更新时必须原样回传。")


class ResourceRef(BaseModel):
    """删除操作的响应体。

    只返回被删除记录的主键：记录已不存在，返回完整内容会误导前端以为它仍然可读。
    """

    id: UUID = Field(description="已被删除记录的主键。")


class ProfileLink(BaseModel):
    """公开链接。"""

    label: str = Field(min_length=1, max_length=50, description="链接名称，例如 GitHub。")
    url: str = Field(min_length=1, max_length=2048, description="链接地址。")


# --------------------------------------------------------------------------------------------
# 证据
# --------------------------------------------------------------------------------------------


class EvidenceCreate(BaseModel):
    """创建证据的请求体。"""

    source_type: EvidenceSourceType = Field(description="证据来源类别。")
    title: str = Field(min_length=1, max_length=200, description="证据标题。")
    content: str | None = Field(default=None, description="证据内容或说明。")
    source_url: str | None = Field(default=None, max_length=2048, description="可核验的外部链接。")
    source_hash: str | None = Field(default=None, max_length=128, description="来源内容哈希。")
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        description="证据的可核验程度；无凭据的证据不要标为 VERIFIED。",
    )


class EvidenceUpdate(BaseModel):
    """局部更新证据的请求体。"""

    version: int = Field(ge=1, description="当前版本号；不一致返回 409。")
    source_type: EvidenceSourceType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    source_url: str | None = Field(default=None, max_length=2048)
    source_hash: str | None = Field(default=None, max_length=128)
    verification_status: VerificationStatus | None = None


class EvidenceRead(EditableRead):
    """证据响应体。"""

    source_type: EvidenceSourceType
    title: str
    content: str | None
    source_url: str | None
    source_hash: str | None
    verification_status: VerificationStatus
    archived_at: datetime | None = Field(description="非空表示已归档，默认不参与事实引用。")


# --------------------------------------------------------------------------------------------
# 技能
# --------------------------------------------------------------------------------------------


class SkillCreate(BaseModel):
    """创建技能的请求体。"""

    name: str = Field(min_length=1, max_length=100, description="技能名称，保留原始书写。")
    category: str | None = Field(default=None, max_length=64, description="技能分类。")
    proficiency: SkillProficiency | None = Field(default=None, description="熟练度分级，仅用于展示与排序。")
    years_of_experience: Decimal | None = Field(default=None, ge=0, le=60, description="使用年限。")
    source_evidence_id: UUID | None = Field(default=None, description="支撑该技能的来源证据。")
    claim_status: ClaimStatus = Field(
        default=ClaimStatus.UNVERIFIED,
        description="验证状态；标为 VERIFIED 时必须同时提供 source_evidence_id。",
    )
    sort_order: int = Field(default=0, ge=0, description="列表展示顺序。")

    @model_validator(mode="after")
    def _check_verification_requires_evidence(self) -> SkillCreate:
        """校验"已验证"必须挂证据。

        返回:
            SkillCreate: 校验通过的自身实例。

        异常:
            ValueError: 标记为 VERIFIED 但未提供证据时抛出，FastAPI 会转为 422。
        """
        if self.claim_status is ClaimStatus.VERIFIED and self.source_evidence_id is None:
            raise ValueError("claim_status 为 VERIFIED 时必须提供 source_evidence_id。")
        return self


class SkillUpdate(BaseModel):
    """局部更新技能的请求体。"""

    version: int = Field(ge=1, description="当前版本号；不一致返回 409。")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=64)
    proficiency: SkillProficiency | None = None
    years_of_experience: Decimal | None = Field(default=None, ge=0, le=60)
    source_evidence_id: UUID | None = None
    claim_status: ClaimStatus | None = None
    sort_order: int | None = Field(default=None, ge=0)


class SkillRead(EditableRead):
    """技能响应体。"""

    name: str
    name_normalized: str = Field(description="服务端规范化后的技能名，用于同档案内唯一性判断。")
    category: str | None
    proficiency: SkillProficiency | None
    years_of_experience: Decimal | None
    source_evidence_id: UUID | None
    claim_status: ClaimStatus
    sort_order: int


# --------------------------------------------------------------------------------------------
# 工作经历、项目、教育、语言
# --------------------------------------------------------------------------------------------


class ExperienceCreate(BaseModel):
    """创建工作经历的请求体。"""

    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200, description="职位名称。")
    location: str | None = Field(default=None, max_length=100)
    start_date: date = Field(description="入职时间。")
    end_date: date | None = Field(default=None, description="离职时间；为空表示当前仍在职。")
    responsibilities: str | None = Field(default=None, description="职责描述。")
    achievements: str | None = Field(default=None, description="成果描述，鼓励量化。")
    source_evidence_id: UUID | None = None
    sort_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_date_order(self) -> ExperienceCreate:
        """校验结束日期不早于开始日期，避免依赖数据库报错。

        返回:
            ExperienceCreate: 校验通过的自身实例。

        异常:
            ValueError: 日期顺序非法时抛出。
        """
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date 不得早于 start_date。")
        return self


class ExperienceUpdate(BaseModel):
    """局部更新工作经历的请求体。"""

    version: int = Field(ge=1)
    company: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    responsibilities: str | None = None
    achievements: str | None = None
    source_evidence_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=0)


class ExperienceRead(EditableRead):
    """工作经历响应体。"""

    company: str
    title: str
    location: str | None
    start_date: date
    end_date: date | None
    responsibilities: str | None
    achievements: str | None
    source_evidence_id: UUID | None
    sort_order: int


class ProjectCreate(BaseModel):
    """创建项目的请求体。"""

    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=100, description="本人角色。")
    description: str | None = None
    tech_stack: list[str] = Field(default_factory=list[str], description="技术栈标签。")
    url: str | None = Field(default=None, max_length=2048)
    start_date: date | None = None
    end_date: date | None = None
    source_evidence_id: UUID | None = None
    sort_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_date_order(self) -> ProjectCreate:
        """校验结束日期不早于开始日期。

        返回:
            ProjectCreate: 校验通过的自身实例。

        异常:
            ValueError: 两个日期都存在且顺序非法时抛出。
        """
        if self.start_date is not None and self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date 不得早于 start_date。")
        return self


class ProjectUpdate(BaseModel):
    """局部更新项目的请求体。"""

    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    description: str | None = None
    tech_stack: list[str] | None = None
    url: str | None = Field(default=None, max_length=2048)
    start_date: date | None = None
    end_date: date | None = None
    source_evidence_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=0)


class ProjectRead(EditableRead):
    """项目响应体。"""

    name: str
    role: str | None
    description: str | None
    tech_stack: list[str]
    url: str | None
    start_date: date | None
    end_date: date | None
    source_evidence_id: UUID | None
    sort_order: int


class EducationCreate(BaseModel):
    """创建教育经历的请求体。"""

    school: str = Field(min_length=1, max_length=200)
    major: str | None = Field(default=None, max_length=200)
    degree: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    source_evidence_id: UUID | None = None
    sort_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_date_order(self) -> EducationCreate:
        """校验结束日期不早于开始日期。

        返回:
            EducationCreate: 校验通过的自身实例。

        异常:
            ValueError: 两个日期都存在且顺序非法时抛出。
        """
        if self.start_date is not None and self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date 不得早于 start_date。")
        return self


class EducationUpdate(BaseModel):
    """局部更新教育经历的请求体。"""

    version: int = Field(ge=1)
    school: str | None = Field(default=None, min_length=1, max_length=200)
    major: str | None = Field(default=None, max_length=200)
    degree: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    source_evidence_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=0)


class EducationRead(EditableRead):
    """教育经历响应体。"""

    school: str
    major: str | None
    degree: str | None
    start_date: date | None
    end_date: date | None
    source_evidence_id: UUID | None
    sort_order: int


class LanguageCreate(BaseModel):
    """创建语言能力的请求体。"""

    language: str = Field(min_length=1, max_length=64)
    level: str | None = Field(default=None, max_length=64, description="水平描述，例如 CET-6。")
    note: str | None = None
    source_evidence_id: UUID | None = None
    sort_order: int = Field(default=0, ge=0)


class LanguageUpdate(BaseModel):
    """局部更新语言能力的请求体。"""

    version: int = Field(ge=1)
    language: str | None = Field(default=None, min_length=1, max_length=64)
    level: str | None = Field(default=None, max_length=64)
    note: str | None = None
    source_evidence_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=0)


class LanguageRead(EditableRead):
    """语言能力响应体。"""

    language: str
    level: str | None
    note: str | None
    source_evidence_id: UUID | None
    sort_order: int


# --------------------------------------------------------------------------------------------
# 求职偏好
# --------------------------------------------------------------------------------------------


class PreferenceUpsert(BaseModel):
    """创建或整体替换求职偏好的请求体。"""

    target_locations: list[str] = Field(default_factory=list[str], description="目标地点标签。")
    job_types: list[str] = Field(default_factory=list[str], description="职位类型标签。")
    salary_min: int | None = Field(default=None, ge=0, description="期望薪资下限，按月计。")
    salary_max: int | None = Field(default=None, ge=0, description="期望薪资上限，按月计。")
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3, description="ISO 4217 币种。")
    remote_preference: RemotePreference | None = None
    exclusions: list[str] = Field(default_factory=list[str], description="排除条件标签。")
    version: int | None = Field(
        default=None,
        ge=1,
        description="偏好已存在时必须提供当前版本号用于乐观锁；首次创建时留空。",
    )

    @model_validator(mode="after")
    def _check_salary_range(self) -> PreferenceUpsert:
        """校验薪资上限不低于下限。

        返回:
            PreferenceUpsert: 校验通过的自身实例。

        异常:
            ValueError: 上下限都存在且顺序非法时抛出。
        """
        if self.salary_min is not None and self.salary_max is not None and self.salary_max < self.salary_min:
            raise ValueError("salary_max 不得小于 salary_min。")
        return self


class PreferenceRead(EditableRead):
    """求职偏好响应体。"""

    target_locations: list[str]
    job_types: list[str]
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    remote_preference: RemotePreference | None
    exclusions: list[str]


# --------------------------------------------------------------------------------------------
# 档案根与修订
# --------------------------------------------------------------------------------------------


class ProfileCreate(BaseModel):
    """创建（首次填写）个人档案根信息的请求体。"""

    full_name: str = Field(min_length=1, max_length=100, description="姓名。")
    headline: str | None = Field(default=None, max_length=200)
    summary: str | None = None
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=100)
    links: list[ProfileLink] = Field(default_factory=list[ProfileLink])


class ProfileUpdate(BaseModel):
    """局部更新个人档案根信息的请求体。"""

    version: int = Field(ge=1, description="当前版本号；不一致返回 409。")
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    headline: str | None = Field(default=None, max_length=200)
    summary: str | None = None
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=100)
    links: list[ProfileLink] | None = None


class ProfileRead(EditableRead):
    """个人档案聚合响应体。

    单用户小数据量下，一次返回全部子项比让前端发十几个请求更简单可靠。
    """

    singleton_key: str
    full_name: str
    headline: str | None
    summary: str | None
    email: str | None
    phone: str | None
    city: str | None
    links: list[ProfileLink]
    evidences: list[EvidenceRead]
    skills: list[SkillRead]
    experiences: list[ExperienceRead]
    projects: list[ProjectRead]
    educations: list[EducationRead]
    languages: list[LanguageRead]
    preference: PreferenceRead | None


class RevisionCreate(BaseModel):
    """创建资料修订的请求体。"""

    reason: str = Field(min_length=1, max_length=200, description="创建原因，例如 生成投递简历。")


class RevisionRead(ORMModel):
    """资料修订响应体。

    修订不可变，因此没有 `updated_at` 与 `version`。
    """

    id: UUID
    profile_id: UUID
    revision_no: int
    snapshot_json: dict[str, Any] = Field(description="当时的事实内容与来源证据 ID。")
    reason: str
    created_at: datetime
