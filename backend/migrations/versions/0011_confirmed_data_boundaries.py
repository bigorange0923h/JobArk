"""落实归档、来源冻结、当前 JD 与投递材料锁定的已确认边界。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACT_TABLES = (
    "profile_skills", "profile_experiences", "profile_projects", "profile_educations", "profile_languages",
)


def upgrade() -> None:
    """只新增边界和确定性关联；旧来源缺失明确标记，不用当前内容补历史。"""
    for table in FACT_TABLES:
        op.add_column(table, sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True,
                                      comment="日常删除执行归档，不改变历史修订与版本。"))
    op.drop_constraint("uq_profile_skills_profile_id_name_normalized", "profile_skills", type_="unique")
    op.create_index("uq_profile_skills_active_name", "profile_skills",
                    ["profile_id", "name_normalized"], unique=True,
                    postgresql_where=sa.text("archived_at IS NULL"))

    op.add_column("resume_drafts", sa.Column("source_profile_revision_id", sa.UUID(), nullable=True,
                      comment="候选生成时固定的资料依据；无依据的人工空白稿可空。"))
    op.create_foreign_key("fk_resume_drafts_source_profile_revision_id_profile_revisions",
                          "resume_drafts", "profile_revisions", ["source_profile_revision_id"], ["id"],
                          ondelete="RESTRICT")
    op.create_index("ix_resume_drafts_source_profile_revision_id", "resume_drafts", ["source_profile_revision_id"])
    # 基线或已确认版本才提供可确定的依据；人工历史稿保持空，不猜测“生成时的最新档案”。
    op.execute(
        "UPDATE resume_drafts d SET source_profile_revision_id = v.profile_revision_id "
        "FROM resume_versions v WHERE v.id = COALESCE(d.base_resume_version_id, d.confirmed_resume_version_id)"
    )
    op.add_column("resume_version_evidences", sa.Column(
        "source_snapshot_json", postgresql.JSONB(), nullable=False,
        server_default=sa.text("'{\"history_missing\": true}'::jsonb"),
        comment="当时实际使用的来源冻结内容；旧数据缺失不得由当前来源反推。",
    ))

    op.add_column("job_postings", sa.Column("current_snapshot_id", sa.UUID(), nullable=True))
    op.create_unique_constraint("uq_job_snapshots_posting_id_id", "job_snapshots", ["posting_id", "id"])
    op.create_foreign_key("fk_job_postings_current_snapshot", "job_postings", "job_snapshots",
                          ["id", "current_snapshot_id"], ["posting_id", "id"], ondelete="RESTRICT")
    op.create_index("ix_job_postings_current_snapshot_id", "job_postings", ["current_snapshot_id"])
    # 旧结构没有重复观察记录，首次设置只能采用当时已保存的最新快照，不修改其采集时间。
    op.execute(
        "UPDATE job_postings p SET current_snapshot_id = "
        "(SELECT s.id FROM job_snapshots s WHERE s.posting_id=p.id "
        "ORDER BY s.captured_at DESC, s.created_at DESC, s.id DESC LIMIT 1)"
    )
    op.create_check_constraint("match_kind_requires_version", "match_results",
                              "(match_kind='PROFILE' AND resume_version_id IS NULL) OR "
                              "(match_kind='RESUME' AND resume_version_id IS NOT NULL)")
    op.create_check_constraint("parse_result_state", "job_parse_results",
                              "(status='PARSED' AND result_json IS NOT NULL AND result_json <> 'null'::jsonb AND failure_code IS NULL) OR "
                              "(status='FAILED' AND (result_json IS NULL OR result_json = 'null'::jsonb) AND failure_code IS NOT NULL)")

    op.alter_column("applications", "resume_version_id", existing_type=sa.UUID(), nullable=True)
    op.add_column("applications", sa.Column("material_locked_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE applications a SET material_locked_at = "
        "(SELECT min(e.occurred_at) FROM application_events e "
        "WHERE e.application_id=a.id AND e.to_status='APPLIED')"
    )
    op.create_check_constraint("materials_require_version", "applications",
                              "(current_status NOT IN ('READY_TO_APPLY','APPLIED','CONTACTED','INTERVIEWING',"
                              "'OFFERED','REJECTED') AND material_locked_at IS NULL) OR resume_version_id IS NOT NULL")
    op.create_check_constraint("applied_requires_lock", "applications",
                              "current_status NOT IN ('APPLIED','CONTACTED','INTERVIEWING','OFFERED','REJECTED') "
                              "OR material_locked_at IS NOT NULL")
    # 同步 0010 表继承的公共列注释，避免自动迁移持续报告已确认模型的注释差异。
    for table in ("exclusion_evaluations", "exclusion_exceptions", "exclusion_policies"):
        op.alter_column(table, "created_at", comment="记录创建时间（UTC）。")
    op.alter_column("exclusion_policies", "updated_at", comment="最后更新时间（UTC），由 ORM 在更新时刷新。")
    op.alter_column("exclusion_policies", "version", comment="乐观锁版本号；每次更新自增，接口提交旧值即返回 409。")
    op.alter_column("job_opportunities", "outsourcing_arrangement",
                    comment="用户确认的岗位安排：OUTSOURCING、DIRECT 或未知。")
    op.add_column("application_events", sa.Column("payload_json", postgresql.JSONB(), nullable=False,
                                                 server_default=sa.text("'{}'::jsonb"),
                                                 comment="按事件类型校验的输入引用与确认，不保存无约束事实。"))


def downgrade() -> None:
    """撤回新增结构；存在归档、空材料或不可恢复旧约束时由数据库拒绝，避免静默丢失。"""
    # 不能删除新语义后把归档事实重新变成有效事实，也不能丢掉事件材料历史。
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM application_events WHERE payload_json <> '{}'::jsonb) "
        "OR EXISTS (SELECT 1 FROM resume_version_evidences WHERE source_snapshot_json <> '{\"history_missing\": true}'::jsonb) "
        "THEN RAISE EXCEPTION '0011 contains retained history; downgrade refused'; END IF; END $$"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM resume_drafts d WHERE d.source_profile_revision_id "
        "IS DISTINCT FROM (SELECT v.profile_revision_id FROM resume_versions v "
        "WHERE v.id=COALESCE(d.base_resume_version_id,d.confirmed_resume_version_id))) "
        "OR EXISTS (SELECT 1 FROM job_postings p WHERE p.current_snapshot_id "
        "IS DISTINCT FROM (SELECT s.id FROM job_snapshots s WHERE s.posting_id=p.id "
        "ORDER BY s.captured_at DESC,s.created_at DESC,s.id DESC LIMIT 1)) "
        "THEN RAISE EXCEPTION 'fixed basis or current observation history exists; downgrade refused'; END IF; END $$"
    )
    for table in FACT_TABLES:
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {table} WHERE archived_at IS NOT NULL) "
                   "THEN RAISE EXCEPTION 'archived facts exist; downgrade refused'; END IF; END $$")
    for table in ("exclusion_evaluations", "exclusion_exceptions", "exclusion_policies"):
        op.alter_column(table, "created_at", comment=None)
    op.alter_column("exclusion_policies", "updated_at", comment=None)
    op.alter_column("exclusion_policies", "version", comment=None)
    op.alter_column("job_opportunities", "outsourcing_arrangement", comment="用户确认的岗位安排。")
    op.drop_column("application_events", "payload_json")
    op.drop_constraint(op.f("ck_applications_applied_requires_lock"), "applications", type_="check")
    op.drop_constraint(op.f("ck_applications_materials_require_version"), "applications", type_="check")
    op.drop_column("applications", "material_locked_at")
    op.alter_column("applications", "resume_version_id", existing_type=sa.UUID(), nullable=False)
    op.drop_constraint(op.f("ck_job_parse_results_parse_result_state"), "job_parse_results", type_="check")
    op.drop_constraint(op.f("ck_match_results_match_kind_requires_version"), "match_results", type_="check")
    op.drop_constraint("fk_job_postings_current_snapshot", "job_postings", type_="foreignkey")
    op.drop_index("ix_job_postings_current_snapshot_id", table_name="job_postings")
    op.drop_column("job_postings", "current_snapshot_id")
    op.drop_constraint("uq_job_snapshots_posting_id_id", "job_snapshots", type_="unique")
    op.drop_column("resume_version_evidences", "source_snapshot_json")
    op.drop_constraint("fk_resume_drafts_source_profile_revision_id_profile_revisions", "resume_drafts", type_="foreignkey")
    op.drop_index("ix_resume_drafts_source_profile_revision_id", table_name="resume_drafts")
    op.drop_column("resume_drafts", "source_profile_revision_id")
    op.drop_index("uq_profile_skills_active_name", table_name="profile_skills")
    op.create_unique_constraint("uq_profile_skills_profile_id_name_normalized", "profile_skills",
                               ["profile_id", "name_normalized"])
    for table in FACT_TABLES:
        op.drop_column(table, "archived_at")
