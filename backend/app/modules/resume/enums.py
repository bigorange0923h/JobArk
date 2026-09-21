"""Resume 领域的枚举取值。

这些取值同时是数据库 CHECK 约束的取值集合（见 `app/core/models.py` 的 `enum_column_type`）：
新增取值必须同时修改本文件与迁移，否则写入会在数据库层被拒绝——这是有意的，
它保证"简历状态只能取约定值"不依赖应用层是否记得校验。
"""

from enum import StrEnum


class ResumeStatus(StrEnum):
    """简历方向的状态。

    归档而不是删除：简历版本会被历史投递引用（`Application` 只能引用 `ResumeVersion`），
    物理删除会让历史记录指向不存在的对象。
    """

    ACTIVE = "ACTIVE"
    """可继续维护与生成新版本。"""

    ARCHIVED = "ARCHIVED"
    """已停用；默认不出现在列表中，但历史版本仍可原样查看。"""


class DraftStatus(StrEnum):
    """AI 或人工候选稿的状态。

    状态机的核心约束：确认（`CONFIRMED`）时**新建** `ResumeVersion`，绝不覆盖已有版本；
    未确认的候选内容不会影响任何正式版本。
    """

    DRAFT = "DRAFT"
    """已生成，等待用户确认或丢弃。"""

    CONFIRMED = "CONFIRMED"
    """已确认，并已据此生成一个新的不可变版本。"""

    DISCARDED = "DISCARDED"
    """用户主动丢弃；不生成版本。"""

    FAILED = "FAILED"
    """生成失败；保留安全错误码，不生成版本，也不留下貌似有效的内容。"""


class ResumeSection(StrEnum):
    """简历文档的可排序模块。

    模块顺序与显隐是简历文档自身的内容，因此进入 `document_json` 而不是数据库列：
    它们随模板与简历方向变化，不需要被查询或约束。
    """

    SUMMARY = "SUMMARY"
    """个人简介。"""

    EXPERIENCES = "EXPERIENCES"
    """工作经历。"""

    PROJECTS = "PROJECTS"
    """项目经历。"""

    SKILLS = "SKILLS"
    """技能。"""

    EDUCATIONS = "EDUCATIONS"
    """教育经历。"""

    LANGUAGES = "LANGUAGES"
    """语言能力。"""
