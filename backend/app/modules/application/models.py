"""申请事实与不可变状态事件；当前状态只作为事件投影。"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import CreatedAtMixin, EditableMixin, UuidPrimaryKeyMixin, enum_column_type


class ApplicationStatus(StrEnum):
    """人工跟踪的申请阶段，不意味着系统已经向外部提交。"""

    SAVED = "SAVED"
    PREPARING = "PREPARING"
    READY_TO_APPLY = "READY_TO_APPLY"
    APPLIED = "APPLIED"
    CONTACTED = "CONTACTED"
    INTERVIEWING = "INTERVIEWING"
    OFFERED = "OFFERED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


class Application(UuidPrimaryKeyMixin, EditableMixin, Base):
    """一次申请尝试；快照和简历版本在创建后固定。"""

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_opportunity_id", "attempt_no"),)
    job_opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_opportunities.id", ondelete="RESTRICT"), index=True
    )
    job_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_snapshots.id", ondelete="RESTRICT"), index=True)
    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="RESTRICT"), index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer)
    current_status: Mapped[ApplicationStatus] = mapped_column(enum_column_type(ApplicationStatus, "application_status"))


class ApplicationEvent(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """一次不可变状态决定；与申请投影在同一事务提交。"""

    __tablename__ = "application_events"
    __table_args__ = (UniqueConstraint("application_id", "sequence_no"),)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="RESTRICT"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[ApplicationStatus | None] = mapped_column(enum_column_type(ApplicationStatus, "from_status"))
    to_status: Mapped[ApplicationStatus] = mapped_column(enum_column_type(ApplicationStatus, "to_status"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(32), default="USER")
    notes: Mapped[str | None] = mapped_column(Text)
