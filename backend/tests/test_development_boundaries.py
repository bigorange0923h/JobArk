"""在开发库的事务内隔离 schema 验证真实迁移与接口，不清表、不持久化测试数据。"""

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database import get_session
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def development_client() -> AsyncIterator[AsyncClient]:
    """使用开发连接，在外层事务内运行迁移和接口；服务 commit 仅释放保存点。"""
    if os.environ.get("JOBARK_VERIFY_DEVELOPMENT_DATABASE") != "1":
        pytest.skip("未显式启用开发库事务验证。")
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool, connect_args={"timeout": 8})
    schema = "jobark_verify_" + uuid.uuid4().hex
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await connection.execute(text("SET LOCAL statement_timeout = '20s'"))
                config = Config(str(ROOT / "alembic.ini"))
                config.set_main_option("script_location", str(ROOT / "migrations"))

                def migrate(sync_connection: Any) -> None:
                    """迁移绑定调用方事务，不允许环境另开开发库连接。"""
                    config.attributes["connection"] = sync_connection
                    command.upgrade(config, "head")
                    command.downgrade(config, "base")
                    command.upgrade(config, "head")

                await connection.run_sync(migrate)
                assert (
                    await connection.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one() == "0011"
                application = create_app()

                async def override_session() -> AsyncIterator[AsyncSession]:
                    """每个请求使用保存点；业务提交不能提交外层事务。"""
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                application.dependency_overrides[get_session] = override_session
                async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
                    yield client
            finally:
                await outer.rollback()
            # schema 连同数据与 DDL 必须已经回滚，不能留下测试目录或业务记录。
            assert (
                await connection.execute(
                    text("SELECT count(*) FROM pg_namespace WHERE nspname=:schema"),
                    {"schema": schema},
                )
            ).scalar_one() == 0
    finally:
        await engine.dispose()


async def saved(client: AsyncClient, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """提交成功请求并验证统一成功契约；失败只打印安全 API 响应。"""
    response = await client.request(method, "/api/v1" + path, json=payload)
    assert response.status_code in (200, 201), response.text
    envelope = response.json()
    assert envelope["success"] is True
    return envelope["data"]


async def baseline(client: AsyncClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """建立仅属于本次事务 schema 的档案、修订与简历方向。"""
    await saved(client, "POST", "/profile", {"full_name": "事务测试"})
    revision = await saved(client, "POST", "/profile/revisions", {"reason": "测试依据"})
    resume = await saved(client, "POST", "/resumes", {"name": "事务测试"})
    version = await saved(
        client,
        "POST",
        f"/resumes/{resume['id']}/versions",
        {
            "profile_revision_id": revision["id"],
            "document": {"basics": {"full_name": "事务测试"}},
            "created_reason": "事务测试",
        },
    )
    return revision, resume, version


async def test_archive_retains_history_and_conflicting_restore(development_client: AsyncClient) -> None:
    """历史引用不阻止归档，同名恢复冲突且不覆盖当前事实。"""
    client = development_client
    await saved(client, "POST", "/profile", {"full_name": "事务测试"})
    skill = await saved(client, "POST", "/profile/skills", {"name": "Python"})
    revision = await saved(client, "POST", "/profile/revisions", {"reason": "保留历史"})
    archived = await client.delete(f"/api/v1/profile/skills/{skill['id']}?version={skill['version']}")
    assert archived.status_code == 200, archived.text
    profile = (await client.get("/api/v1/profile")).json()["data"]
    assert profile["skills"] == []
    assert revision["snapshot_json"]["skills"][0]["id"] == skill["id"]
    current = await saved(client, "POST", "/profile/skills", {"name": "Python"})
    listing = (await client.get("/api/v1/profile/archived-facts")).json()["data"]["skills"]
    assert listing[0]["id"] == skill["id"]
    conflict = await client.post(
        f"/api/v1/profile/archived-facts/skills/{skill['id']}/restore",
        json={"version": listing[0]["version"]},
    )
    assert conflict.status_code == 409
    assert (await client.get("/api/v1/profile")).json()["data"]["skills"][0]["id"] == current["id"]


async def test_draft_basis_and_frozen_sources(development_client: AsyncClient) -> None:
    """同 ID 内容改变后确认仍沿用原依据；版本来源不随当前证据改写。"""
    client = development_client
    await saved(client, "POST", "/profile", {"full_name": "事务测试"})
    evidence = await saved(
        client,
        "POST",
        "/profile/evidences",
        {
            "source_type": "PROJECT_LINK",
            "title": "来源",
            "content": "原始摘录",
        },
    )
    skill = await saved(
        client,
        "POST",
        "/profile/skills",
        {
            "name": "Python",
            "source_evidence_id": evidence["id"],
        },
    )
    revision = await saved(client, "POST", "/profile/revisions", {"reason": "生成候选"})
    resume = await saved(client, "POST", "/resumes", {"name": "事务测试"})
    draft = await saved(
        client,
        "POST",
        f"/resumes/{resume['id']}/drafts",
        {
            "source_profile_revision_id": revision["id"],
            "document": {
                "basics": {"full_name": "事务测试"},
                "skills": [{"name": "Python", "source_fact_id": skill["id"]}],
            },
        },
    )
    await saved(
        client,
        "PATCH",
        f"/profile/evidences/{evidence['id']}",
        {
            "version": evidence["version"],
            "content": "后来修改的摘录",
        },
    )
    newer = await saved(client, "POST", "/profile/revisions", {"reason": "新来源"})
    rejected = await client.post(
        f"/api/v1/resumes/{resume['id']}/drafts/{draft['id']}/confirm",
        json={
            "version": draft["version"],
            "profile_revision_id": newer["id"],
        },
    )
    assert rejected.status_code == 422
    version = await saved(
        client,
        "POST",
        f"/resumes/{resume['id']}/drafts/{draft['id']}/confirm",
        {
            "version": draft["version"],
            "evidence_ids": [evidence["id"]],
        },
    )
    assert version["profile_revision_id"] == revision["id"]
    assert version["evidence_snapshots"][0]["content"] == "原始摘录"
    assert (
        await client.post(
            f"/api/v1/resumes/{resume['id']}/drafts/{draft['id']}/confirm",
            json={"version": draft["version"]},
        )
    ).status_code == 409


async def test_current_jd_and_application_material_lock(development_client: AsyncClient) -> None:
    """A-B-A 复用当前内容；就绪换材料重新核验，首次已投递后不能解锁。"""
    client = development_client
    _, _resume, version = await baseline(client)
    job = await saved(client, "POST", "/jobs", {"company": {"name": "测试公司"}, "title": "开发", "raw_jd": "内容 A"})
    posting_id = job["postings"][0]["id"]
    original_id = job["latest_snapshot"]["id"]
    path = f"/jobs/{job['id']}/postings/{posting_id}/snapshots"
    second = await saved(client, "POST", path, {"raw_jd": "内容 B"})
    third = await saved(client, "POST", path, {"raw_jd": "内容 A"})
    assert third["id"] == original_id
    current_job = (await client.get(f"/api/v1/jobs/{job['id']}")).json()["data"]
    assert current_job["latest_snapshot"]["id"] == original_id
    application = await saved(
        client,
        "POST",
        "/applications",
        {
            "job_opportunity_id": job["id"],
            "job_snapshot_id": original_id,
        },
    )
    event_path = f"/applications/{application['id']}/events"
    assert (
        await client.post(
            "/api/v1" + event_path,
            json={
                "version": application["version"],
                "status": "APPLIED",
                "confirm_applied": True,
            },
        )
    ).status_code == 422
    application = await saved(
        client,
        "PATCH",
        f"/applications/{application['id']}/materials",
        {
            "version": application["version"],
            "job_snapshot_id": original_id,
            "resume_version_id": version["id"],
        },
    )
    application = await saved(client, "POST", event_path, {"version": application["version"], "status": "PREPARING"})
    application = await saved(
        client, "POST", event_path, {"version": application["version"], "status": "READY_TO_APPLY"}
    )
    unchanged = await saved(
        client,
        "PATCH",
        f"/applications/{application['id']}/materials",
        {
            "version": application["version"],
            "job_snapshot_id": original_id,
            "resume_version_id": version["id"],
        },
    )
    assert unchanged["current_status"] == "READY_TO_APPLY"
    assert unchanged["version"] == application["version"]
    assert len(unchanged["events"]) == len(application["events"])
    application = await saved(
        client,
        "PATCH",
        f"/applications/{application['id']}/materials",
        {
            "version": application["version"],
            "job_snapshot_id": second["id"],
            "resume_version_id": version["id"],
        },
    )
    assert application["current_status"] == "PREPARING"
    assert application["events"][-1]["event_type"] == "MATERIALS_CHANGED"
    # 如实补记外部历史投递可使用旧 JD，不受当前准备核验限制。
    applied = await saved(
        client,
        "POST",
        event_path,
        {
            "version": application["version"],
            "status": "APPLIED",
            "confirm_applied": True,
        },
    )
    assert applied["material_locked_at"] is not None
    assert applied["events"][-1]["payload_json"]["inputs"]["job_snapshot_id"] == second["id"]
    denied = await client.patch(
        f"/api/v1/applications/{application['id']}/materials",
        json={
            "version": applied["version"],
            "job_snapshot_id": original_id,
            "resume_version_id": None,
        },
    )
    assert denied.status_code == 409
    dashboard = await client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["data"]["application_count"] == 1


async def test_archived_experience_retains_project_link(development_client: AsyncClient) -> None:
    """归档经历不解绑项目；保留关系可编辑，新关联被拒绝，恢复后正常回显。"""
    client = development_client
    await baseline(client)
    experience = await saved(
        client,
        "POST",
        "/profile/experiences",
        {
            "company": "归档公司",
            "title": "开发",
            "start_date": "2020-01-01",
        },
    )
    project = await saved(
        client,
        "POST",
        "/profile/projects",
        {
            "name": "关联项目",
            "experience_id": experience["id"],
        },
    )
    assert "归档公司" in project["experience_summary"]
    archived = await client.delete(f"/api/v1/profile/experiences/{experience['id']}?version={experience['version']}")
    assert archived.status_code == 200
    profile = (await client.get("/api/v1/profile")).json()["data"]
    assert profile["experiences"] == []
    assert profile["projects"][0]["experience_id"] == experience["id"]
    assert "已归档" in profile["projects"][0]["experience_summary"]
    project = await saved(
        client,
        "PATCH",
        f"/profile/projects/{project['id']}",
        {
            "version": project["version"],
            "description": "更新说明",
            "experience_id": experience["id"],
        },
    )
    assert "已归档" in project["experience_summary"]
    rejected = await client.post("/api/v1/profile/projects", json={"name": "新项目", "experience_id": experience["id"]})
    assert rejected.status_code == 422
    restored = await saved(
        client,
        "POST",
        f"/profile/archived-facts/experiences/{experience['id']}/restore",
        {
            "version": experience["version"] + 1,
        },
    )
    assert restored["archived_at"] is None
    assert (await client.get(f"/api/v1/profile/revisions/{uuid.uuid4()}")).status_code == 404


async def test_archived_source_keeps_existing_reference(development_client: AsyncClient) -> None:
    """来源归档后保留已有关系可编辑；新事实不可引用，修订仍冻结活动事实的来源。"""
    client = development_client
    await baseline(client)
    source = await saved(
        client,
        "POST",
        "/profile/evidences",
        {
            "source_type": "MANUAL_DECLARATION",
            "title": "测试来源",
            "content": "原文",
        },
    )
    language = await saved(
        client,
        "POST",
        "/profile/languages",
        {
            "language": "英语",
            "source_evidence_id": source["id"],
        },
    )
    assert (await client.delete(f"/api/v1/profile/evidences/{source['id']}?version=1")).status_code == 200
    await saved(
        client,
        "PATCH",
        f"/profile/languages/{language['id']}",
        {
            "version": 1,
            "level": "熟练",
            "source_evidence_id": source["id"],
        },
    )
    assert (
        await client.post(
            "/api/v1/profile/languages",
            json={
                "language": "日语",
                "source_evidence_id": source["id"],
            },
        )
    ).status_code == 422
    revision = await saved(client, "POST", "/profile/revisions", {"reason": "归档来源保留"})
    assert revision["snapshot_json"]["evidences"][0]["content"] == "原文"


async def test_draft_first_binding_and_baseline_inheritance(development_client: AsyncClient) -> None:
    """无事实的手工草稿允许第一次绑定；之后不能更换依据，基线草稿自动继承。"""
    client = development_client
    revision, resume, version = await baseline(client)
    document = {"basics": {"full_name": "手工稿"}}
    draft = await saved(client, "POST", f"/resumes/{resume['id']}/drafts", {"document": document})
    assert draft["source_profile_revision_id"] is None
    draft = await saved(
        client,
        "PATCH",
        f"/resumes/{resume['id']}/drafts/{draft['id']}",
        {
            "version": draft["version"],
            "source_profile_revision_id": revision["id"],
            "document": document,
        },
    )
    assert draft["source_profile_revision_id"] == revision["id"]
    newer = await saved(client, "POST", "/profile/revisions", {"reason": "新修订"})
    assert (
        await client.patch(
            f"/api/v1/resumes/{resume['id']}/drafts/{draft['id']}",
            json={
                "version": draft["version"],
                "source_profile_revision_id": newer["id"],
                "document": document,
            },
        )
    ).status_code == 422
    inherited = await saved(
        client,
        "POST",
        f"/resumes/{resume['id']}/drafts",
        {
            "document": document,
            "base_resume_version_id": version["id"],
        },
    )
    assert inherited["source_profile_revision_id"] == revision["id"]


async def test_parse_outputs_do_not_write_legacy_snapshot(development_client: AsyncClient) -> None:
    """重复解析保存独立不可变产物，快照历史内嵌列不发生新的双写。"""
    client = development_client
    job = await saved(
        client,
        "POST",
        "/jobs",
        {
            "company": {"name": "解析测试"},
            "title": "开发",
            "raw_jd": "需要 Python 开发经验。",
        },
    )
    snapshot = job["latest_snapshot"]
    path = f"/job-snapshots/{snapshot['id']}/parses"
    first = await saved(client, "POST", path, {"engine": "LOCAL"})
    second = await saved(client, "POST", path, {"engine": "LOCAL"})
    assert first["id"] != second["id"]
    assert first["status"] == second["status"] == "PARSED"
    assert len((await client.get("/api/v1" + path)).json()["data"]) == 2
    latest = (await client.get(f"/api/v1/jobs/{job['id']}")).json()["data"]["latest_snapshot"]
    assert latest["parsed_json"] is None
    assert latest["parse_status"] == "NOT_REQUESTED"
    assert (await client.post("/api/v1" + path, json={"engine": "AI"})).status_code == 422
