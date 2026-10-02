"""招聘平台本地导入契约：候选确认、去重、不可变回执与冲突保护。"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.modules.job import import_service

URL = "https://www.linkedin.com/jobs/view/1234567890/?trackingId=discard"
BODY = "负责服务设计、开发、测试与维护。"


def _preview(client: TestClient, content: str = BODY, url: str = URL) -> dict[str, Any]:
    """保存本地正文候选；失败时仅展示安全响应，不打印原始页面。"""
    response = client.post("/api/v1/job-imports/preview", json={"url": url, "mode": "TEXT", "content": content})
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json()["data"])


def _payload(candidate: dict[str, Any], **changes: str) -> dict[str, Any]:
    """补全缺失字段，模拟用户实际核对；来源身份不由前端提交。"""
    fields = {**candidate["fields"]}
    fields["company_name"] = fields["company_name"] or "示例科技"
    fields["title"] = fields["title"] or "后端工程师"
    fields.update(changes)
    return {"version": candidate["version"], "confirm": True, "fields": fields}


def _confirm(client: TestClient, candidate: dict[str, Any], **changes: str) -> dict[str, Any]:
    """确认并返回固定产物引用。"""
    response = client.post(f"/api/v1/job-imports/{candidate['id']}/confirm", json=_payload(candidate, **changes))
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json()["data"])


@pytest.mark.parametrize(
    ("url", "source", "external_id"),
    [
        (URL, "LINKEDIN", "1234567890"),
        ("https://www.indeed.com/viewjob?jk=0123456789abcdef&from=search", "INDEED", "0123456789abcdef"),
        ("https://www.zhipin.com/job_detail/abcdefghijk123.html?lid=12", "BOSS", "abcdefghijk123"),
        ("https://jobs.51job.com/shanghai/123456789.html?jobid=123456789", "FIFTYONEJOB", "123456789"),
    ],
)
def test_four_sources_require_review_before_business_write(
    db_client: TestClient,
    url: str,
    source: str,
    external_id: str,
) -> None:
    """四站识别均来自 URL；预览不能创建机会，确认后来源和正文可回读。"""
    candidate = _preview(db_client, url=url)
    assert candidate["source"] == source
    assert candidate["external_id"] == external_id
    assert candidate["fields"]["title"] == ""
    assert candidate["reviewed_fields"] is None
    assert candidate["status"] == "PENDING"
    assert db_client.get("/api/v1/jobs").json()["data"] == []
    receipt = _confirm(db_client, candidate, company_name="核对公司", title="核对职位")
    job = db_client.get(f"/api/v1/jobs/{receipt['opportunity_id']}").json()["data"]
    assert job["title"] == "核对职位"
    assert job["postings"][0]["source"] == source
    assert job["postings"][0]["external_id"] == external_id
    assert job["latest_snapshot"]["raw_jd"] == BODY
    saved = db_client.get(f"/api/v1/job-imports/{candidate['id']}").json()["data"]
    assert saved["fields"] == candidate["fields"]
    assert saved["reviewed_fields"]["company_name"] == "核对公司"
    assert saved["status"] == "CONFIRMED"
    assert saved["version"] == 2
    assert saved["confirmed_snapshot_id"] == receipt["snapshot_id"]


def test_same_source_reuses_snapshot_and_does_not_overwrite_metadata(db_client: TestClient) -> None:
    """A→B→A复用旧快照，已有分类/备注与人工机会信息不受导入覆盖。"""
    original = _preview(db_client)
    first = _confirm(db_client, original)
    job_id = first["opportunity_id"]
    update = db_client.patch(
        f"/api/v1/jobs/{job_id}",
        json={
            "version": 1,
            "notes": "人工备注",
            "title": "已确认标题",
            "location": " 上海 ",
            "employment_type": "全职",
        },
    )
    assert update.status_code == 200
    second_candidate = _preview(db_client, content="新增系统设计职责。")
    assert second_candidate["target_posting_id"] == first["posting_id"]
    assert second_candidate["fields"]["title"] == "已确认标题"
    changed = db_client.post(
        f"/api/v1/job-imports/{second_candidate['id']}/confirm",
        json=_payload(
            second_candidate,
            title="外部不可信标题",
        ),
    )
    assert changed.status_code == 422
    second = _confirm(db_client, second_candidate)
    third = _confirm(db_client, _preview(db_client))
    assert first["opportunity_id"] == second["opportunity_id"] == third["opportunity_id"]
    assert first["posting_id"] == second["posting_id"] == third["posting_id"]
    assert first["snapshot_id"] == third["snapshot_id"] != second["snapshot_id"]
    job = db_client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["title"] == "已确认标题"
    assert job["notes"] == "人工备注"
    assert job["employment_type"] == "全职"
    assert job["location"] == " 上海 "
    assert len(db_client.get("/api/v1/jobs").json()["data"]) == 1


def test_confirmation_retry_keeps_original_receipt_after_later_update(db_client: TestClient) -> None:
    """旧候选重试不回读新JD、不再次写入；不同载荷或版本拒绝。"""
    candidate = _preview(db_client)
    first = _confirm(db_client, candidate)
    later = _confirm(db_client, _preview(db_client, content="后来更新的职责。"))
    assert later["snapshot_id"] != first["snapshot_id"]
    assert _confirm(db_client, candidate) == first
    detail = db_client.get(f"/api/v1/jobs/{first['opportunity_id']}").json()["data"]
    assert detail["latest_snapshot"]["id"] == later["snapshot_id"]
    assert detail["postings"][0]["version"] == 3
    altered = db_client.post(f"/api/v1/job-imports/{candidate['id']}/confirm", json=_payload(candidate, raw_jd="改写"))
    assert altered.status_code == 409
    payload = _payload(candidate)
    payload["version"] = 2
    assert db_client.post(f"/api/v1/job-imports/{candidate['id']}/confirm", json=payload).status_code == 409


def test_racing_first_previews_and_stale_existing_preview_are_rejected(db_client: TestClient) -> None:
    """两个首次预览不能重复创建；已有页面变化后的旧预览不能覆盖更新。"""
    first, competing = _preview(db_client), _preview(db_client, content="并发来源")
    receipt = _confirm(db_client, first)
    stale = db_client.post(f"/api/v1/job-imports/{competing['id']}/confirm", json=_payload(competing))
    assert stale.status_code == 409
    assert db_client.get(f"/api/v1/job-imports/{competing['id']}").json()["data"]["status"] == "PENDING"
    older, newer = _preview(db_client, content="旧预览"), _preview(db_client, content="新预览")
    latest = _confirm(db_client, newer)
    assert db_client.post(f"/api/v1/job-imports/{older['id']}/confirm", json=_payload(older)).status_code == 409
    jobs = db_client.get("/api/v1/jobs").json()["data"]
    assert len(jobs) == 1
    assert jobs[0]["id"] == receipt["opportunity_id"]
    assert jobs[0]["latest_snapshot_id"] == latest["snapshot_id"]


def test_validation_missing_confirmation_and_not_found(db_client: TestClient) -> None:
    """必填、身份伪造和明确确认校验失败，未知候选返回404且没有业务写入。"""
    candidate = _preview(db_client)
    path = f"/api/v1/job-imports/{candidate['id']}/confirm"
    payload = _payload(candidate)
    payload["confirm"] = False
    assert db_client.post(path, json=payload).status_code == 422
    assert db_client.post(path, json={"version": 1, "confirm": True, "fields": candidate["fields"]}).status_code == 422
    forged = _payload(candidate)
    forged["source"] = "MANUAL"
    assert db_client.post(path, json=forged).status_code == 422
    missing = f"/api/v1/job-imports/{uuid4()}"
    assert db_client.get(missing).status_code == 404
    assert db_client.post(missing + "/confirm", json=_payload(candidate)).status_code == 404
    assert db_client.get("/api/v1/jobs").json()["data"] == []


def test_html_candidate_uses_safe_fields_and_preserves_review_audit(db_client: TestClient) -> None:
    """结构化字段形成候选，脚本被移除，人工修订不能覆盖原始候选。"""
    structured = {
        "@type": "JobPosting",
        "title": "后端岗位",
        "hiringOrganization": {"name": "页面公司"},
        "url": URL,
        "description": "<p>开发服务</p><script>secret()</script>",
    }
    # HTML 中的脚本结束标签必须转义，JSON 字符串本身不改变 HTML 解析器的边界。
    content = '<script type="application/ld+json">' + json.dumps(structured).replace("</", "<\\/") + "</script>"
    response = db_client.post("/api/v1/job-imports/preview", json={"url": URL, "mode": "HTML", "content": content})
    assert response.status_code == 201, response.text
    candidate = response.json()["data"]
    assert candidate["fields"] == {
        "company_name": "页面公司",
        "title": "后端岗位",
        "location": None,
        "raw_jd": "开发服务",
    }
    assert "secret" not in response.text
    receipt = _confirm(db_client, candidate, company_name="人工核对公司", raw_jd="开发服务与测试")
    audit = db_client.get(f"/api/v1/job-imports/{candidate['id']}").json()["data"]
    assert audit["fields"] == candidate["fields"]
    assert audit["reviewed_fields"]["company_name"] == "人工核对公司"
    assert audit["confirmed_snapshot_id"] == receipt["snapshot_id"]


@pytest.mark.parametrize(
    "change",
    [
        {"confirm": "true"},
        {"confirm": 1},
        {"fields": {"raw_jd": "正文\x00"}},
        {"fields": {"company_name": "错误\ud800"}},
    ],
)
def test_invalid_confirmation_encoding_or_flag_is_rejected(db_client: TestClient, change: dict[str, Any]) -> None:
    """显式确认必须是真布尔值，无效编码/NUL只能安全失败。"""
    candidate = _preview(db_client)
    payload = _payload(candidate)
    if "fields" in change:
        payload["fields"].update(change["fields"])
    else:
        payload.update(change)
    response = db_client.post(
        f"/api/v1/job-imports/{candidate['id']}/confirm",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert db_client.get("/api/v1/jobs").json()["data"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "https://example.com/jobs/1", "mode": "TEXT", "content": BODY},
        {"url": URL, "mode": "HTML", "content": "<script>alert(1)</script>"},
        {"url": URL, "mode": "TEXT", "content": " "},
        {"url": URL, "mode": "TEXT", "content": "中" * 349526},
        {"url": URL, "mode": "TEXT", "content": BODY, "source": "BOSS"},
        {"url": URL, "mode": "TEXT", "content": "正文\x00"},
    ],
)
def test_invalid_preview_has_safe_error_and_no_business_write(db_client: TestClient, payload: dict[str, Any]) -> None:
    """拒绝无正文、错误链接、超字节上限及额外来源字段；错误不回显全文。"""
    response = db_client.post("/api/v1/job-imports/preview", json=payload)
    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["meta"]["request_id"]
    assert db_client.get("/api/v1/jobs").json()["data"] == []


@pytest.mark.parametrize("during_wait", [False, True])
def test_expired_candidate_before_or_after_lock_is_rejected(
    db_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    during_wait: bool,
) -> None:
    """候选开始时或等待锁时过期均不能写入。"""
    candidate = _preview(db_client)
    now = datetime.now(UTC)
    clock = Mock(side_effect=[now, now + timedelta(hours=25)] if during_wait else None)
    if not during_wait:
        clock.return_value = now + timedelta(hours=25)
    monkeypatch.setattr(import_service, "datetime", SimpleNamespace(now=clock))
    response = db_client.post(f"/api/v1/job-imports/{candidate['id']}/confirm", json=_payload(candidate))
    assert response.status_code == 409
    assert db_client.get("/api/v1/jobs").json()["data"] == []
    assert db_client.get(f"/api/v1/job-imports/{candidate['id']}").json()["data"]["status"] == "PENDING"


def test_advisory_lock_timeout_rolls_back_and_allows_retry(db_client: TestClient) -> None:
    """另一连接占据来源锁时有界失败，释放后同候选仍能确认；不写任何公共业务表。"""
    candidate = _preview(db_client)
    portal = cast(Any, db_client).portal
    assert portal is not None

    async def acquire() -> tuple[AsyncEngine, AsyncConnection]:
        """独立只读连接只持事务锁，不访问候选或正式数据。"""
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        connection = await engine.connect()
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {
                "identity": "job-import:LINKEDIN:1234567890",
            },
        )
        return engine, connection

    engine, connection = portal.call(acquire)

    async def release() -> None:
        """回滚释放来源锁，关闭连接与引擎。"""
        await connection.rollback()
        await connection.close()
        await engine.dispose()

    try:
        response = db_client.post(f"/api/v1/job-imports/{candidate['id']}/confirm", json=_payload(candidate))
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CONFLICT"
        assert db_client.get("/api/v1/jobs").json()["data"] == []
        assert db_client.get(f"/api/v1/job-imports/{candidate['id']}").json()["data"]["status"] == "PENDING"
    finally:
        portal.call(release)
    assert _confirm(db_client, candidate)["snapshot_id"]
