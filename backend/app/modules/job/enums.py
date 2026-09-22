"""职位领域的稳定枚举。

V1 先支持人工维护职位与 JD；来源、解析与页面状态拆开保存，避免把"暂未解析"误写成
"解析失败"，或把页面下线误当作职位机会本身已经关闭。
"""

from enum import StrEnum


class JobSource(StrEnum):
    """职位页面来源。"""

    MANUAL = "MANUAL"


class OpportunityStatus(StrEnum):
    """职位机会的人工管理状态。"""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PostingStatus(StrEnum):
    """招聘页面的可用状态。"""

    ACTIVE = "ACTIVE"
    UNAVAILABLE = "UNAVAILABLE"


class SnapshotParseStatus(StrEnum):
    """某份 JD 快照的结构化解析状态。"""

    NOT_REQUESTED = "NOT_REQUESTED"
    PARSED = "PARSED"
    FAILED = "FAILED"
