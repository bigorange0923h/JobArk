"""申请接口输入与响应，确认标记由调用方显式提交。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.responses import EditableRead, ORMModel

from .models import ApplicationStatus


class ApplicationCreate(BaseModel):
    """创建申请；已有尝试时必须确认重新申请。"""

    model_config = ConfigDict(extra="forbid")
    job_opportunity_id: UUID = Field(description="职位机会。")
    job_snapshot_id: UUID = Field(description="属于该职位的不可变 JD 快照。")
    resume_version_id: UUID = Field(description="申请使用的不可变简历版本。")
    confirm_repeat: bool = Field(default=False, description="明确同意创建新的申请尝试。")


class ApplicationTransition(BaseModel):
    """状态变更，记录已投递时要求人工确认。"""

    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, description="当前乐观锁版本。")
    status: ApplicationStatus = Field(description="目标阶段。")
    confirm_applied: bool = Field(default=False, description="确认已在平台完成投递；本接口不投递。")
    notes: str | None = Field(default=None, max_length=10000, description="此次状态变更备注。")


class ApplicationEventRead(ORMModel):
    """按序号排列的申请时间线条目。"""

    id: UUID
    sequence_no: int
    event_type: str
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    occurred_at: datetime
    notes: str | None


class ApplicationRead(EditableRead):
    """申请与可追溯输入引用。"""

    job_opportunity_id: UUID
    job_snapshot_id: UUID
    resume_version_id: UUID
    attempt_no: int
    current_status: ApplicationStatus


class ApplicationDetail(ApplicationRead):
    """申请详情以及服务端允许的下一步状态。"""

    events: list[ApplicationEventRead]
    allowed_statuses: list[ApplicationStatus]
