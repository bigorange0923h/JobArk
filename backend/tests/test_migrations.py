"""迁移链路的集成验证。

应用与测试共用配置的 PostgreSQL 数据库；每个用例在独立随机 schema 内反复执行
`upgrade`/`downgrade`，而不是只断言迁移脚本存在。连接仅搜索该 schema，既有业务表不参与测试。

注意:
    这些测试必须是同步的。Alembic 的异步 `env.py` 内部调用 `asyncio.run`，
    若在已运行的事件循环中调用会直接报错。
"""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HEAD = "0012"


async def _assert_migration_schema(database_url: str) -> None:
    """迁移前确认当前连接只搜索夹具提供的 schema；不读取或降级业务版本表。"""
    dsn = make_url(database_url).query["dsn"]
    assert isinstance(dsn, str)
    expected_schema = parse_qs(urlsplit(dsn).query)["search_path"][0]
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            schema, search_schemas = (
                await connection.execute(text("SELECT current_schema(), current_schemas(false)"))
            ).one()
            assert schema == expected_schema
            assert search_schemas == [expected_schema]
    finally:
        await engine.dispose()


async def _read_current_revision(database_url: str) -> str | None:
    """读取隔离 schema 当前的迁移版本，不回退到业务 schema。

    参数:
        database_url: 带随机 schema 搜索路径的同库连接串。

    返回:
        str | None: 当前版本号；尚未执行过任何迁移（版本表不存在）时为 None。

    注意:
        引擎在同一事件循环内创建与释放：跨 `asyncio.run` 释放会让 asyncpg 连接归属错误的循环。
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            try:
                result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            except ProgrammingError:
                # 版本表不存在，等价于停留在基线之前。
                return None
            return result.scalar_one_or_none()
    finally:
        await engine.dispose()


def _current_revision(database_url: str) -> str | None:
    """同步读取当前迁移版本，供同步测试使用。

    参数:
        database_url: 目标数据库连接串。

    返回:
        str | None: 当前版本号。
    """
    return asyncio.run(_read_current_revision(database_url))


@pytest.fixture
def alembic_config(test_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    """把迁移环境限定在本用例随机 schema，并保证前后都处于基线状态。

    参数:
        test_database_url: 函数级随机 schema 连接串，与应用使用同一数据库。
        monkeypatch: 用于临时设置连接串环境变量。

    返回:
        Iterator[Config]: 指向 `backend/alembic.ini` 的配置。

    注意:
        `get_settings` 带缓存，切换搜索路径后必须清除，避免迁移仍使用业务 schema。
    """
    monkeypatch.setenv("JOBARK_DATABASE_URL", test_database_url)
    get_settings.cache_clear()

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))

    asyncio.run(_assert_migration_schema(test_database_url))
    command.downgrade(config, "base")
    try:
        yield config
    finally:
        command.downgrade(config, "base")
        get_settings.cache_clear()


def test_upgrade_from_empty_database_reaches_head(alembic_config: Config, test_database_url: str) -> None:
    """空 schema 不读取同库业务版本、约束或索引，执行 upgrade 后到达最新版本。"""
    assert _current_revision(test_database_url) is None
    assert asyncio.run(_foreign_key_names(test_database_url)) == set()
    assert asyncio.run(_index_definitions(test_database_url, "ai_models")) == []
    command.upgrade(alembic_config, "head")

    assert _current_revision(test_database_url) == EXPECTED_HEAD


def test_upgrade_is_idempotent(alembic_config: Config, test_database_url: str) -> None:
    """重复执行 upgrade 不应失败或改变版本。"""
    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")

    assert _current_revision(test_database_url) == EXPECTED_HEAD


def test_downgrade_returns_to_empty_database(alembic_config: Config, test_database_url: str) -> None:
    """downgrade 到基线应移除版本记录，使数据库回到未迁移状态。"""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    assert _current_revision(test_database_url) is None


def test_upgrade_downgrade_upgrade_cycle_is_repeatable(alembic_config: Config, test_database_url: str) -> None:
    """完整的升降级循环应可反复执行，验证迁移链路而非单次结果。"""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    assert _current_revision(test_database_url) == EXPECTED_HEAD


async def _foreign_key_names(database_url: str) -> set[str]:
    """只读取当前隔离 schema 的物理外键约束名，不混入业务表约束。

    参数:
        database_url: 目标数据库连接串。

    返回:
        set[str]: 外键约束名集合。
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE constraint_type = 'FOREIGN KEY' AND table_schema = current_schema()"
                )
            )
            return {str(row[0]) for row in result.all()}
    finally:
        await engine.dispose()


# 期望存在的跨表外键。约束名本身编码了"子表_列_目标表"，因此这份清单同时就是引用关系清单。
_EXPECTED_FOREIGN_KEYS = {
    "fk_job_import_candidates_target_posting_id_job_postings",
    "fk_job_import_candidates_confirmed_posting_id_job_postings",
    "fk_job_import_candidates_confirmed_snapshot",
    "fk_job_parse_results_job_snapshot_id_job_snapshots",
    "fk_match_results_job_snapshot_id_job_snapshots",
    "fk_match_results_profile_revision_id_profile_revisions",
    "fk_match_results_resume_version_id_resume_versions",
    "fk_applications_job_opportunity_id_job_opportunities",
    "fk_applications_job_snapshot_id_job_snapshots",
    "fk_applications_resume_version_id_resume_versions",
    "fk_application_events_application_id_applications",
    # Profile：子表与修订指向主档案，事实表指向证据
    "fk_profile_evidences_profile_id_personal_profiles",
    "fk_profile_preferences_profile_id_personal_profiles",
    "fk_profile_revisions_profile_id_personal_profiles",
    "fk_profile_educations_profile_id_personal_profiles",
    "fk_profile_educations_source_evidence_id_profile_evidences",
    "fk_profile_experiences_profile_id_personal_profiles",
    "fk_profile_experiences_source_evidence_id_profile_evidences",
    "fk_profile_languages_profile_id_personal_profiles",
    "fk_profile_languages_source_evidence_id_profile_evidences",
    "fk_profile_projects_profile_id_personal_profiles",
    "fk_profile_projects_experience_id_profile_experiences",
    "fk_profile_projects_source_evidence_id_profile_evidences",
    "fk_profile_skills_profile_id_personal_profiles",
    "fk_profile_skills_source_evidence_id_profile_evidences",
    # Resume：版本指向简历与资料修订，证据关联指向版本与证据，候选稿指向简历与版本
    "fk_resume_versions_resume_id_resumes",
    "fk_resume_versions_profile_revision_id_profile_revisions",
    "fk_resume_version_evidences_resume_version_id_resume_versions",
    "fk_resume_version_evidences_evidence_id_profile_evidences",
    "fk_resume_drafts_resume_id_resumes",
    "fk_resume_drafts_base_resume_version_id_resume_versions",
    "fk_resume_drafts_source_profile_revision_id_profile_revisions",
    "fk_job_postings_current_snapshot",
    "fk_resume_drafts_confirmed_resume_version_id_resume_versions",
    # Job：机会、页面与快照必须保留物理引用完整性。
    "fk_job_opportunities_company_id_companies",
    "fk_job_postings_opportunity_id_job_opportunities",
    "fk_job_snapshots_posting_id_job_postings",
    "fk_exclusion_evaluations_opportunity_id_job_opportunities",
    "fk_exclusion_evaluations_snapshot_id_job_snapshots",
    "fk_exclusion_exceptions_opportunity_id_job_opportunities",
    "fk_exclusion_exceptions_snapshot_id_job_snapshots",
    # AI 配置：模型必须挂在服务商下，服务商删除时级联清理其模型。
    "fk_ai_models_provider_id_ai_providers",
}


def test_schema_has_expected_foreign_keys(alembic_config: Config, test_database_url: str) -> None:
    """迁移产物必须包含全部跨表外键。

    为什么需要这条断言：外键在模型与迁移中各出现一次，删掉迁移里的约束不会有任何报错，
    数据库会悄悄失去引用完整性，并让依赖外键推断连接条件的 ORM 关系在运行到该查询时才失败。
    断言"关键外键存在"比断言数量更能定位缺失的是哪一条。
    """
    command.upgrade(alembic_config, "head")

    assert asyncio.run(_foreign_key_names(test_database_url)) == _EXPECTED_FOREIGN_KEYS


async def _index_definitions(database_url: str, table_name: str) -> list[str]:
    """读取当前隔离 schema 中指定表的索引定义，不混入同名业务表。

    参数:
        database_url: 目标数据库连接串。
        table_name: 目标表名。

    返回:
        list[str]: `pg_indexes.indexdef` 文本，可直接判断唯一性与条件。
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() AND tablename = :table"),
                {"table": table_name},
            )
            return [str(row[0]) for row in result.all()]
    finally:
        await engine.dispose()


def test_ai_model_schema_has_single_default_index(alembic_config: Config, test_database_url: str) -> None:
    """AI 模型表必须有"至多一个默认模型"的部分唯一索引。

    为什么需要这条断言：默认模型的唯一性是业务核心约束，而应用层事务只能降低并发写入
    产生两个默认模型的概率，不能彻底排除；真正的保证来自数据库的部分唯一索引。
    该索引一旦从迁移里被删掉，功能测试仍然可能通过，问题只会在并发或手工写库时暴露。
    """
    command.upgrade(alembic_config, "head")

    definitions = asyncio.run(_index_definitions(test_database_url, "ai_models"))
    assert any("UNIQUE" in item and "is_default" in item for item in definitions)
