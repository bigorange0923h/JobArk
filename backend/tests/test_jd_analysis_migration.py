"""新迁移的随机 schema 集成回归；业务表不参与，连接失败不能算通过。"""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


@pytest.mark.asyncio
async def test_jd_only_upgrade_and_refused_loss(test_database_url: str) -> None:
    """先验证空 schema 升降级，再验证 JD-only 回退拒绝且记录保留。"""
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:

            def migrate(sync: Connection, direction: str, revision: str) -> None:
                """只用夹具隔离连接，不允许迁移环境另连业务库。"""
                config.attributes["connection"] = sync
                if direction == "upgrade":
                    command.upgrade(config, revision)
                else:
                    command.downgrade(config, revision)

            await connection.run_sync(migrate, "upgrade", "head")
            await connection.run_sync(migrate, "downgrade", "0013")
            await connection.run_sync(migrate, "upgrade", "head")
            id = uuid4()
            await connection.execute(text("INSERT INTO job_opportunities (id) VALUES (:id)"), {"id": id})
            savepoint = await connection.begin_nested()
            with pytest.raises(DBAPIError, match="JD-only opportunities exist"):
                await connection.run_sync(migrate, "downgrade", "0013")
            await savepoint.rollback()
            assert (
                await connection.execute(
                    text("SELECT company_id,title FROM job_opportunities WHERE id=:id"), {"id": id}
                )
            ).one() == (None, None)

            # ORM 与新增物理列/外键必须同源，空 schema 的迁移不得产生额外差异。
            def check(sync: Connection) -> None:
                """在固定随机 schema 比较当前 ORM 与迁移产物。"""
                config.attributes["connection"] = sync
                command.check(config)

            await connection.run_sync(check)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_refinement_preserves_legacy_data_and_refuses_loss(test_database_url: str) -> None:
    """旧学历和策略原样保留；新确认字段有内容时禁止降级丢失。"""
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:

            def migrate(sync: Connection, direction: str, revision: str) -> None:
                """所有迁移均绑定隔离连接，不触碰业务 schema。"""
                config.attributes["connection"] = sync
                if direction == "upgrade":
                    command.upgrade(config, revision)
                else:
                    command.downgrade(config, revision)

            await connection.run_sync(migrate, "upgrade", "0016")
            profile_id, education_id, preference_id = uuid4(), uuid4(), uuid4()
            await connection.execute(
                text("INSERT INTO personal_profiles(id,full_name) VALUES (:id,'测试')"), {"id": profile_id}
            )
            await connection.execute(
                text(
                    "INSERT INTO profile_educations(id,profile_id,school,degree) "
                    "VALUES (:id,:profile,'学校','本科（非全日制）')"
                ),
                {"id": education_id, "profile": profile_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO profile_preferences(id,profile_id,salary_min,salary_max,salary_currency) "
                    "VALUES (:id,:profile,20000,35000,'CNY')"
                ),
                {"id": preference_id, "profile": profile_id},
            )
            await connection.run_sync(migrate, "upgrade", "head")
            assert (
                await connection.execute(text("SELECT degree,degree_level,study_mode FROM profile_educations"))
            ).one() == ("本科（非全日制）", None, None)
            assert (
                await connection.execute(
                    text("SELECT salary_min,salary_max,role_keywords,acceptable_salary_min FROM profile_preferences")
                )
            ).one() == (20000, 35000, [], None)
            await connection.execute(text("UPDATE profile_educations SET study_mode='PART_TIME'"))
            savepoint = await connection.begin_nested()
            with pytest.raises(DBAPIError, match="refinement inputs exist"):
                await connection.run_sync(migrate, "downgrade", "0016")
            await savepoint.rollback()
            assert await connection.scalar(text("SELECT study_mode FROM profile_educations")) == "PART_TIME"
            await connection.execute(text("UPDATE profile_educations SET study_mode=NULL"))
            await connection.run_sync(migrate, "downgrade", "0016")
            assert await connection.scalar(text("SELECT degree FROM profile_educations")) == "本科（非全日制）"
    finally:
        await engine.dispose()
