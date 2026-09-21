"""Resume 领域的请求与响应模型。

设计要点：

- `document_json` 的结构由 `ResumeDocument` 固定：字段名稳定，才可能让 A4 渲染、AI 改写和
  "未编造事实"校验都基于同一份契约，而不是各自解释一团自由 JSON。
- 每个条目可携带 `source_fact_id` 指回 Profile 事实。手写内容允许留空，AI 生成的内容将来必须
  逐条可追溯；把溯源放进结构里，才可能在后续机械校验，而不是只靠提示词约束。
- 文档是**自包含**的：链接、熟练度等字段使用可读文本而不是引用 Profile 的枚举。历史版本必须
  在 Profile 之后继续变化时仍可原样反序列化，因此文档不能依赖其他模块的枚举取值集合。
- 联系方式单独成字段而不是混入 `basics`：构建 AI 或匹配输入时，剔除联系方式应当是一次整体
  字段删除，而不是逐字段过滤——逐字段过滤总会有漏掉的新字段。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.responses import EditableRead, ORMModel

from .enums import DraftStatus, ResumeSection, ResumeStatus
from .models import DEFAULT_GENERATOR_NAME

RESUME_RENDER_SCHEMA_VERSION = 1
"""当前简历文档结构版本。

它是"用哪套规则解释 document_json"的开关：结构发生不兼容变化时必须递增，
旧版本仍按其自身版本号渲染，而不是被新规则误解。
"""

DEFAULT_CONFIRM_REASON = "确认候选稿生成新版本"
"""候选稿确认时的默认创建原因。"""

DEFAULT_SECTION_ORDER: tuple[ResumeSection, ...] = (
    ResumeSection.SUMMARY,
    ResumeSection.EXPERIENCES,
    ResumeSection.PROJECTS,
    ResumeSection.SKILLS,
    ResumeSection.EDUCATIONS,
    ResumeSection.LANGUAGES,
)
"""默认模块顺序，代表一份常规简历的排版次序。"""


# --------------------------------------------------------------------------------------------
# 简历文档结构
# --------------------------------------------------------------------------------------------


class ResumeLink(BaseModel):
    """简历上的公开链接。"""

    label: str = Field(min_length=1, max_length=50, description="链接名称，例如 GitHub。")
    url: str = Field(min_length=1, max_length=2048, description="链接地址。")


class ResumeContact(BaseModel):
    """联系方式。

    刻意独立于 `ResumeBasics`：联系方式出现在简历成品上是必要的，但不应进入 AI 或匹配的输入。
    独立成字段后，剔除动作是删除一个字段，不会随 `basics` 增加字段而失效。
    """

    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)


class ResumeBasics(BaseModel):
    """简历头部信息。"""

    full_name: str = Field(min_length=1, max_length=100, description="姓名。")
    headline: str | None = Field(default=None, max_length=200, description="一句话头衔。")
    city: str | None = Field(default=None, max_length=100)
    links: list[ResumeLink] = Field(default_factory=list[ResumeLink])


class ResumeTextBlock(BaseModel):
    """带溯源的文本块，例如个人简介。"""

    text: str = Field(min_length=1, description="正文。")
    source_fact_id: UUID | None = Field(
        default=None,
        description="正文所依据的 Profile 事实主键；手写内容可以为空。",
    )


class ResumeExperienceItem(BaseModel):
    """简历上的一段工作经历。"""

    source_fact_id: UUID | None = Field(default=None, description="对应的 Profile 工作经历。")
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = Field(default=None, description="为空表示当前仍在职。")
    highlights: list[str] = Field(
        default_factory=list[str],
        description="面向该简历方向的要点，逐条对应职责或成果。",
    )


class ResumeProjectItem(BaseModel):
    """简历上的一个项目。"""

    source_fact_id: UUID | None = Field(default=None, description="对应的 Profile 项目。")
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    description: str | None = None
    tech_stack: list[str] = Field(default_factory=list[str])
    url: str | None = Field(default=None, max_length=2048)


class ResumeSkillItem(BaseModel):
    """简历上的一项技能。

    熟练度保存为可读文本而不是 Profile 的枚举：文档必须自包含，档案侧枚举取值变化
    不应让历史简历无法反序列化。
    """

    source_fact_id: UUID | None = Field(default=None, description="对应的 Profile 技能。")
    name: str = Field(min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=64)
    proficiency: str | None = Field(default=None, max_length=32, description="展示用分级，例如 ADVANCED。")


class ResumeEducationItem(BaseModel):
    """简历上的一段教育经历。"""

    source_fact_id: UUID | None = Field(default=None, description="对应的 Profile 教育经历。")
    school: str = Field(min_length=1, max_length=200)
    major: str | None = Field(default=None, max_length=200)
    degree: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    end_date: date | None = None


class ResumeLanguageItem(BaseModel):
    """简历上的一项语言能力。"""

    source_fact_id: UUID | None = Field(default=None, description="对应的 Profile 语言能力。")
    language: str = Field(min_length=1, max_length=64)
    level: str | None = Field(default=None, max_length=64)


class ResumeDocument(BaseModel):
    """简历文档的完整结构。

    模块顺序与显隐属于文档内容而不是数据库列：它们随模板与简历方向变化，
    不需要被查询或约束，放进文档可以让历史版本保持自洽。
    """

    schema_version: Literal[1] = Field(
        default=RESUME_RENDER_SCHEMA_VERSION,
        description="文档结构版本；服务端据此决定渲染与解析规则。",
    )
    basics: ResumeBasics
    contact: ResumeContact | None = Field(default=None, description="联系方式；构建 AI 输入时应整体剔除。")
    summary: ResumeTextBlock | None = None
    experiences: list[ResumeExperienceItem] = Field(default_factory=list[ResumeExperienceItem])
    projects: list[ResumeProjectItem] = Field(default_factory=list[ResumeProjectItem])
    skills: list[ResumeSkillItem] = Field(default_factory=list[ResumeSkillItem])
    educations: list[ResumeEducationItem] = Field(default_factory=list[ResumeEducationItem])
    languages: list[ResumeLanguageItem] = Field(default_factory=list[ResumeLanguageItem])
    section_order: list[ResumeSection] = Field(
        default_factory=lambda: list(DEFAULT_SECTION_ORDER),
        description="模块展示顺序；必须恰好包含全部模块各一次，使渲染结果确定。",
    )
    hidden_sections: list[ResumeSection] = Field(
        default_factory=list[ResumeSection],
        description="不展示的模块；内容保留，随时可以恢复显示。",
    )

    @model_validator(mode="after")
    def _check_section_configuration(self) -> ResumeDocument:
        """校验模块顺序与显隐配置。

        返回:
            ResumeDocument: 校验通过的自身实例。

        异常:
            ValueError: 顺序含重复/缺漏，或隐藏列表含未在顺序中出现的模块时抛出，FastAPI 转为 422。

        注意:
            要求 `section_order` 恰好是全部模块的一个排列，而不是"允许缺省"：缺省的语义
            （"没写的模块展示还是不展示"）永远说不清，会让前端与渲染器各自猜测。
            正因为顺序必须是全集，`hidden_sections` 不可能包含未列入顺序的模块，
            因此这里不再重复判断子集关系——那是无法触发的校验。
        """
        if len(set(self.section_order)) != len(self.section_order):
            raise ValueError("section_order 不得包含重复模块。")
        if set(self.section_order) != set(ResumeSection):
            raise ValueError("section_order 必须恰好包含全部简历模块各一次。")

        if len(set(self.hidden_sections)) != len(self.hidden_sections):
            raise ValueError("hidden_sections 不得包含重复模块。")
        return self


# --------------------------------------------------------------------------------------------
# 简历方向
# --------------------------------------------------------------------------------------------


class ResumeCreate(BaseModel):
    """创建简历方向的请求体。"""

    name: str = Field(min_length=1, max_length=200, description="简历方向名称。")
    target_direction: str | None = Field(default=None, max_length=200, description="目标方向。")


class ResumeUpdate(BaseModel):
    """局部更新简历方向的请求体。"""

    version: int = Field(ge=1, description="当前版本号；不一致返回 409。")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    target_direction: str | None = Field(default=None, max_length=200)
    status: ResumeStatus | None = Field(default=None, description="置为 ARCHIVED 即为停用。")


class ResumeRead(EditableRead):
    """简历方向响应体。"""

    name: str
    target_direction: str | None
    status: ResumeStatus


# --------------------------------------------------------------------------------------------
# 简历版本
# --------------------------------------------------------------------------------------------


class ResumeVersionCreate(BaseModel):
    """创建简历版本的请求体。

    不接受 `version_no` 与 `render_schema_version`：前者由服务端在同一简历内自增，
    后者取自文档自身的 `schema_version`。让客户端提交它们只会制造不一致的机会。
    """

    profile_revision_id: UUID = Field(description="该版本依据的资料修订；必须已存在。")
    document: ResumeDocument = Field(description="结构化简历文档。")
    created_reason: str = Field(min_length=1, max_length=200, description="创建原因。")
    evidence_ids: list[UUID] = Field(
        default_factory=list[UUID],
        description="该版本实际使用的证据；重复项会被合并。",
    )


class ResumeVersionRead(ORMModel):
    """简历版本响应体。

    `document_json` 按原始结构返回而不重新校验成 `ResumeDocument`：历史版本必须能被原样查看，
    若用当前模型反序列化，未来结构升级会让旧版本读不出来——那正是版本号要避免的情况。
    """

    id: UUID
    resume_id: UUID
    version_no: int
    profile_revision_id: UUID
    document_json: dict[str, Any] = Field(description="结构由 render_schema_version 决定。")
    render_schema_version: int
    created_reason: str
    created_at: datetime = Field(description="创建时间（UTC）。")
    evidence_ids: list[UUID] = Field(default_factory=list[UUID], description="该版本关联的证据主键。")


# --------------------------------------------------------------------------------------------
# 候选稿
# --------------------------------------------------------------------------------------------


class ResumeDraftCreate(BaseModel):
    """创建候选稿的请求体。

    V1 由用户或后续 AI 流程调用同一接口；`generator_name` 区分来源，
    使"候选内容是谁生成的"不依赖旁路记录。
    """

    document: ResumeDocument = Field(description="候选内容。")
    base_resume_version_id: UUID | None = Field(
        default=None,
        description="改写基线版本；为空表示从零生成。必须属于同一份简历。",
    )
    generator_name: str = Field(default=DEFAULT_GENERATOR_NAME, min_length=1, max_length=64)
    generator_version: str | None = Field(default=None, max_length=64)


class ResumeDraftConfirm(BaseModel):
    """确认候选稿的请求体。"""

    version: int = Field(ge=1, description="候选稿当前版本号；不一致返回 409，避免重复确认。")
    profile_revision_id: UUID = Field(
        description="该候选稿依据的资料修订。刻意要求显式提交而不是从基线版本推断："
        "资料可能在候选稿生成之后发生变化，静默沿用旧修订会让新版本指向不准确的输入。",
    )
    created_reason: str = Field(default=DEFAULT_CONFIRM_REASON, min_length=1, max_length=200)
    evidence_ids: list[UUID] = Field(default_factory=list[UUID], description="新版本关联的证据；重复项会被合并。")


class ResumeDraftDiscard(BaseModel):
    """丢弃候选稿的请求体。"""

    version: int = Field(ge=1, description="候选稿当前版本号；不一致返回 409。")


class ResumeDraftRead(EditableRead):
    """候选稿响应体。"""

    resume_id: UUID
    base_resume_version_id: UUID | None
    document_json: dict[str, Any] = Field(description="候选内容；未被确认前不进入任何正式版本。")
    status: DraftStatus
    confirmed_resume_version_id: UUID | None = Field(description="确认后产出的版本主键。")
    generator_name: str
    generator_version: str | None
    failure_code: str | None
    failure_message: str | None
