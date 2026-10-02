"""申请接口输入与响应，确认标记由调用方显式提交。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.responses import EditableRead, ORMModel

from .models import ApplicationStatus


class ApplicationCreate(BaseModel):
    """创建申请；已有尝试时必须确认重新申请。"""

    model_config = ConfigDict(extra="forbid")
    job_opportunity_id: UUID = Field(description="职位机会。")
    job_snapshot_id: UUID = Field(description="属于该职位的不可变 JD 快照。")
    resume_version_id: UUID | None = Field(default=None, description="准备阶段可空；就绪和已投递必须选择正式版本。")
    confirm_repeat: bool = Field(default=False, description="收到 DUPLICATE_APPLICATION 后，明确同意创建新的申请尝试。")


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
    event_type: str = Field(description="创建、材料调整或状态变更。")
    payload_json: dict[str, Any] = Field(description="对应事件的输入引用与确认；旧事件可能为空。")
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
    resume_version_id: UUID | None
    material_locked_at: datetime | None = Field(description="首次确认已投递时锁定材料，之后不可清除。")
    attempt_no: int
    current_status: ApplicationStatus


class ApplicationDetail(ApplicationRead):
    """申请详情以及服务端允许的下一步状态。"""

    events: list[ApplicationEventRead]
    allowed_statuses: list[ApplicationStatus]


class MaterialReferences(BaseModel):
    """事件中的固定输入引用；不携带可变正文。"""

    model_config = ConfigDict(extra="forbid")
    job_snapshot_id: UUID
    resume_version_id: UUID | None


class CreatedPayload(BaseModel):
    """申请创建时的准备输入。"""

    model_config = ConfigDict(extra="forbid")
    inputs: MaterialReferences


class MaterialsChangedPayload(BaseModel):
    """一次材料替换的前后引用，供时间线复算。"""

    model_config = ConfigDict(extra="forbid")
    before: MaterialReferences
    after: MaterialReferences


class AppliedPayload(CreatedPayload):
    """用户已完成外部投递的明确确认与实际输入。"""

    confirm_applied: bool = Field(description="必须为真；不是外部发送授权。")


class ApplicationMaterials(BaseModel):
    """只允许修改未锁定申请的准备材料；版本过期返回 409。"""

    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    job_snapshot_id: UUID
    resume_version_id: UUID | None = None
