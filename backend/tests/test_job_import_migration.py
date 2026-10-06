"""默认复用开发连接的真实迁移回归：只在事务随机 schema 操作，不更改业务 schema。"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MigrationSandbox:
    """调用方持有的隔离连接及 MANUAL 基线标识；迁移不另开连接或提交外层事务。"""

    connection: AsyncConnection
    config: Config
    schema: str
    company_id: uuid.UUID
    opportunity_id: uuid.UUID
    posting_id: uuid.UUID
    snapshot_id: uuid.UUID


async def _migrate(
    sandbox: MigrationSandbox, direction: Literal["upgrade", "downgrade", "check"], revision: str
) -> None:
    """将 Alembic 显式绑定事务连接；异常由测试保存点回滚，不能连接 public。"""

    def run(sync_connection: Connection) -> None:
        """同步迁移仅使用异步连接提供的同步外观。"""
        sandbox.config.attributes["connection"] = sync_connection
        if direction == "upgrade":
            command.upgrade(sandbox.config, revision)
        elif direction == "downgrade":
            command.downgrade(sandbox.config, revision)
        else:
            command.check(sandbox.config)

    await sandbox.connection.run_sync(run)


async def _baseline(sandbox: MigrationSandbox) -> dict[str, Any]:
    """读取升级前完整的业务行，包含时间、版本和当前指向以验证没有隐式改写。"""
    result = await sandbox.connection.execute(
        text(
            "SELECT jsonb_build_object('company', to_jsonb(c), 'opportunity', to_jsonb(o), "
            "'posting', to_jsonb(p), 'snapshot', to_jsonb(s)) "
            "FROM companies c JOIN job_opportunities o ON o.company_id=c.id "
            "JOIN job_postings p ON p.opportunity_id=o.id "
            "JOIN job_snapshots s ON s.posting_id=p.id WHERE p.id=:posting_id"
        ),
        {"posting_id": sandbox.posting_id},
    )
    return result.scalar_one()


@pytest_asyncio.fixture
async def migration_sandbox() -> AsyncIterator[MigrationSandbox]:
    """默认在开发连接的事务随机 schema 建立 0011 基线；退出回滚数据、DDL 和版本表。"""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool, connect_args={"timeout": 8})
    schema = "jobark_import_verify_" + uuid.uuid4().hex
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await connection.execute(text("SET LOCAL statement_timeout = '20s'"))
                assert (await connection.execute(text("SELECT current_schema()"))).scalar_one() == schema
                config = Config(str(ROOT / "alembic.ini"))
                config.set_main_option("script_location", str(ROOT / "migrations"))
                sandbox = MigrationSandbox(connection, config, schema, *(uuid.uuid4() for _ in range(4)))
                await _migrate(sandbox, "upgrade", "0011")
                await connection.execute(
                    text("INSERT INTO companies (id,name,name_normalized) VALUES (:id,'原有公司','原有公司')"),
                    {"id": sandbox.company_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO job_opportunities (id,company_id,title,location,notes) "
                        "VALUES (:id,:company_id,'原有职位','上海','升级前人工备注')"
                    ),
                    {"id": sandbox.opportunity_id, "company_id": sandbox.company_id},
                )
                await connection.execute(
                    text("INSERT INTO job_postings (id,opportunity_id,source) VALUES (:id,:opportunity_id,'MANUAL')"),
                    {"id": sandbox.posting_id, "opportunity_id": sandbox.opportunity_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO job_snapshots (id,posting_id,content_hash,raw_jd) "
                        "VALUES (:id,:posting_id,:hash,'升级前 JD 内容')"
                    ),
                    {"id": sandbox.snapshot_id, "posting_id": sandbox.posting_id, "hash": "a" * 64},
                )
                await connection.execute(
                    text("UPDATE job_postings SET current_snapshot_id=:snapshot_id WHERE id=:posting_id"),
                    {"snapshot_id": sandbox.snapshot_id, "posting_id": sandbox.posting_id},
                )
                yield sandbox
            finally:
                await outer.rollback()
            assert (
                await connection.execute(
                    text("SELECT count(*) FROM pg_namespace WHERE nspname=:schema"), {"schema": schema}
                )
            ).scalar_one() == 0
    finally:
        await engine.dispose()


async def _insert_candidate(sandbox: MigrationSandbox, **overrides: Any) -> None:
    """插入约束测试候选；默认是合法待确认内容，仅在本次隔离 schema 中存在。"""
    parameters: dict[str, Any] = {
        "id": uuid.uuid4(),
        "target_posting_id": None,
        "observed_posting_version": None,
        "status": "PENDING",
        "reviewed_json": None,
        "confirmed_posting_id": None,
        "confirmed_snapshot_id": None,
    }
    parameters.update(overrides)
    await sandbox.connection.execute(
        text(
            "INSERT INTO job_import_candidates "
            "(id,source,external_id,canonical_url,input_hash,extractor_version,candidate_json,expires_at,"
            "target_posting_id,observed_posting_version,status,reviewed_json,"
            "confirmed_posting_id,confirmed_snapshot_id) "
            "VALUES (:id,'LINKEDIN','1234567890','https://www.linkedin.com/jobs/view/1234567890/',"
            "repeat('b',64),'migration-test','{}'::jsonb,now()+interval '24 hours',"
            ":target_posting_id,:observed_posting_version,:status,CAST(:reviewed_json AS jsonb),"
            ":confirmed_posting_id,:confirmed_snapshot_id)"
        ),
        parameters,
    )


async def test_upgrade_preserves_manual_business_rows_and_matches_models(migration_sandbox: MigrationSandbox) -> None:
    """0011 有业务数据时升至 0012 不改变原行，真实数据库与当前模型无迁移差异。"""
    original = await _baseline(migration_sandbox)
    await _migrate(migration_sandbox, "upgrade", "0012")
    assert await _baseline(migration_sandbox) == original
    assert (
        await migration_sandbox.connection.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one() == "0012"
    assert (
        await migration_sandbox.connection.execute(text("SELECT count(*) FROM job_import_candidates"))
    ).scalar_one() == 0
    await _migrate(migration_sandbox, "upgrade", "head")
    await _migrate(migration_sandbox, "check", "head")


async def test_manual_channel_upgrade_preserves_history_and_refuses_loss(migration_sandbox: MigrationSandbox) -> None:
    """新列只增加空值，真实保存渠道后拒绝降级，清空后可无损回退。"""
    await _migrate(migration_sandbox, "upgrade", "0012")
    original = await _baseline(migration_sandbox)
    await _migrate(migration_sandbox, "upgrade", "0013")
    upgraded = await _baseline(migration_sandbox)
    assert upgraded["company"].pop("description") is None
    assert upgraded["posting"].pop("channel_name") is None
    assert upgraded == original
    await migration_sandbox.connection.execute(
        text("UPDATE job_postings SET channel_name='公司官网' WHERE id=:id"),
        {"id": migration_sandbox.posting_id},
    )
    with pytest.raises(DBAPIError, match="manual channel or company description exists; downgrade refused"):
        async with migration_sandbox.connection.begin_nested():
            await _migrate(migration_sandbox, "downgrade", "0012")
    assert (
        await migration_sandbox.connection.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one() == "0013"
    await migration_sandbox.connection.execute(text("UPDATE job_postings SET channel_name=NULL"))
    await migration_sandbox.connection.execute(text("UPDATE companies SET description='用户介绍'"))
    with pytest.raises(DBAPIError, match="manual channel or company description exists; downgrade refused"):
        async with migration_sandbox.connection.begin_nested():
            await _migrate(migration_sandbox, "downgrade", "0012")
    await migration_sandbox.connection.execute(text("UPDATE companies SET description=NULL"))
    await _migrate(migration_sandbox, "downgrade", "0012")
    assert await _baseline(migration_sandbox) == original


async def test_observed_target_requires_nonnull_version(migration_sandbox: MigrationSandbox) -> None:
    """CHECK 不能以 SQL NULL 放过有目标但无观察版本的候选。"""
    await _migrate(migration_sandbox, "upgrade", "0012")
    with pytest.raises(IntegrityError, match="ck_job_import_candidates_observed_target"):
        async with migration_sandbox.connection.begin_nested():
            await _insert_candidate(migration_sandbox, target_posting_id=migration_sandbox.posting_id)
    assert (
        await migration_sandbox.connection.execute(text("SELECT count(*) FROM job_import_candidates"))
    ).scalar_one() == 0
    await _insert_candidate(
        migration_sandbox, target_posting_id=migration_sandbox.posting_id, observed_posting_version=1
    )


async def test_confirmation_snapshot_must_belong_to_confirmed_posting(migration_sandbox: MigrationSandbox) -> None:
    """已确认页面和快照即使各自存在，也不能跨页面伪造确认产物。"""
    await _migrate(migration_sandbox, "upgrade", "0012")
    other_posting_id = uuid.uuid4()
    await migration_sandbox.connection.execute(
        text("INSERT INTO job_postings (id,opportunity_id,source) VALUES (:id,:opportunity_id,'MANUAL')"),
        {"id": other_posting_id, "opportunity_id": migration_sandbox.opportunity_id},
    )
    with pytest.raises(IntegrityError, match="fk_job_import_candidates_confirmed_snapshot"):
        async with migration_sandbox.connection.begin_nested():
            await _insert_candidate(
                migration_sandbox,
                status="CONFIRMED",
                reviewed_json="{}",
                confirmed_posting_id=other_posting_id,
                confirmed_snapshot_id=migration_sandbox.snapshot_id,
            )
    await _insert_candidate(
        migration_sandbox,
        status="CONFIRMED",
        reviewed_json="{}",
        confirmed_posting_id=migration_sandbox.posting_id,
        confirmed_snapshot_id=migration_sandbox.snapshot_id,
    )


@pytest.mark.parametrize("has_candidate", [True, False], ids=["candidate", "platform-posting"])
async def test_downgrade_refuses_import_data(migration_sandbox: MigrationSandbox, has_candidate: bool) -> None:
    """存在候选或平台页面时分别拒绝降级；失败回滚后版本与业务行仍保留。"""
    await _migrate(migration_sandbox, "upgrade", "0012")
    if has_candidate:
        await _insert_candidate(migration_sandbox)
    else:
        await migration_sandbox.connection.execute(
            text("UPDATE job_postings SET source='LINKEDIN',external_id='1234567890' WHERE id=:id"),
            {"id": migration_sandbox.posting_id},
        )
    original = await _baseline(migration_sandbox)
    with pytest.raises(DBAPIError, match="platform import data exists; downgrade refused"):
        async with migration_sandbox.connection.begin_nested():
            await _migrate(migration_sandbox, "downgrade", "0011")
    assert (
        await migration_sandbox.connection.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one() == "0012"
    assert await _baseline(migration_sandbox) == original
    assert (
        await migration_sandbox.connection.execute(text("SELECT count(*) FROM job_import_candidates"))
    ).scalar_one() == int(has_candidate)


async def test_empty_import_tables_allow_downgrade_and_preserve_manual_data(
    migration_sandbox: MigrationSandbox,
) -> None:
    """无候选和平台页面可降回 0011，MANUAL 数据保持，且恢复仅 MANUAL 的来源约束。"""
    original = await _baseline(migration_sandbox)
    await _migrate(migration_sandbox, "upgrade", "0012")
    await _migrate(migration_sandbox, "downgrade", "0011")
    assert await _baseline(migration_sandbox) == original
    assert (
        await migration_sandbox.connection.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one() == "0011"
    assert (
        await migration_sandbox.connection.execute(text("SELECT to_regclass('job_import_candidates')"))
    ).scalar_one() is None
    with pytest.raises(IntegrityError, match="ck_job_postings_job_source"):
        async with migration_sandbox.connection.begin_nested():
            await migration_sandbox.connection.execute(
                text("UPDATE job_postings SET source='LINKEDIN' WHERE id=:id"), {"id": migration_sandbox.posting_id}
            )
