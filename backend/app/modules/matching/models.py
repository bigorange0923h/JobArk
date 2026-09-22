"""版本化分析产物；输入引用和报告均不可变。"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import CreatedAtMixin, UuidPrimaryKeyMixin


class MatchResult(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """一次固定输入的分析；报告内包含条件、证据、缺口和不确定项。"""

    __tablename__ = "match_results"
    job_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_snapshots.id", ondelete="RESTRICT"), index=True)
    profile_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_revisions.id", ondelete="RESTRICT"), index=True
    )
    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="RESTRICT"), index=True
    )
    match_kind: Mapped[str] = mapped_column(String(16))
    engine_name: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    report_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
