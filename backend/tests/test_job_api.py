"""Job API 集成测试：手工录入、不可变快照与乐观锁边界。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi.testclient import TestClient

from app.modules.job.enums import JobSource
from app.modules.job.models import JobPosting, JobSnapshot
from app.modules.job.service import content_hash


def _manual_payload() -> dict[str, Any]:
    """构造一份最小且真实语义完整的手工职位录入请求。"""
    return {
        "company": {"name": "示例科技", "website_url": "https://example.com", "industry": "软件", "location": "上海"},
        "title": "后端工程师",
        "location": "上海",
        "employment_type": "全职",
        "notes": "来自用户手工记录。",
        "canonical_url": "https://example.com/jobs/1",
        "raw_jd": "负责后端服务设计、实现与维护。",
    }


def _create_job(client: TestClient) -> dict[str, Any]:
    """创建职位并断言成功，供其他用例建立前置状态。"""
    response = client.post("/api/v1/jobs", json=_manual_payload())
    assert response.status_code == 201
    assert response.json()["success"] is True
    return cast(dict[str, Any], response.json()["data"])


def test_manual_job_creates_company_opportunity_posting_and_raw_snapshot(db_client: TestClient) -> None:
    """一次手工录入必须产生四层事实，且解析尚未请求时不得伪造结构化结果。"""
    job = _create_job(db_client)

    assert job["company"]["name"] == "示例科技"
    assert job["company"]["name_normalized"] == "示例科技"
    assert job["status"] == "ACTIVE"
    assert len(job["postings"]) == 1
    assert job["postings"][0]["source"] == "MANUAL"
    assert job["latest_snapshot"]["raw_jd"] == _manual_payload()["raw_jd"]
    assert (
        job["latest_snapshot"]["content_hash"]
        == hashlib.sha256(_manual_payload()["raw_jd"].encode("utf-8")).hexdigest()
    )
    assert job["latest_snapshot"]["parse_status"] == "NOT_REQUESTED"
    assert job["latest_snapshot"]["parsed_json"] is None


def test_list_detail_update_and_snapshot_are_scoped(db_client: TestClient) -> None:
    """列表不泄漏 JD 全文；详情与新的同页快照可回读，更新必须遵循乐观锁。"""
    job = _create_job(db_client)
    job_id = job["id"]
    posting_id = job["postings"][0]["id"]

    listing = db_client.get("/api/v1/jobs")
    assert listing.status_code == 200
    assert listing.json()["data"] == [
        {
            "id": job_id,
            "company_name": "示例科技",
            "title": "后端工程师",
            "location": "上海",
            "employment_type": "全职",
            "status": "ACTIVE",
            "latest_snapshot_id": job["latest_snapshot"]["id"],
            "latest_captured_at": job["latest_snapshot"]["captured_at"],
            "version": 1,
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }
    ]

    updated = db_client.patch(
        f"/api/v1/jobs/{job_id}", json={"version": 1, "status": "ARCHIVED", "notes": "暂不考虑。"}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["status"] == "ARCHIVED"
    assert updated.json()["data"]["version"] == 2

    snapshot = db_client.post(
        f"/api/v1/jobs/{job_id}/postings/{posting_id}/snapshots",
        json={"raw_jd": "职责增加了系统设计与性能优化。"},
    )
    assert snapshot.status_code == 201
    assert snapshot.json()["data"]["parse_status"] == "NOT_REQUESTED"
    detail = db_client.get(f"/api/v1/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["latest_snapshot"]["id"] == snapshot.json()["data"]["id"]


def test_snapshot_reuses_duplicate_content_and_rejects_foreign_posting(db_client: TestClient) -> None:
    """相同快照不能重复；路径中的职位与页面不匹配时必须是 404 而非跨机会写入。"""
    first = _create_job(db_client)
    second_payload = _manual_payload()
    second_payload["company"] = {"name": "另一公司"}
    second_payload["canonical_url"] = "https://example.org/jobs/2"
    second = cast(dict[str, Any], db_client.post("/api/v1/jobs", json=second_payload).json()["data"])
    duplicate = db_client.post(
        f"/api/v1/jobs/{first['id']}/postings/{first['postings'][0]['id']}/snapshots",
        json={"raw_jd": _manual_payload()["raw_jd"]},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["data"]["id"] == first["latest_snapshot"]["id"]
    foreign = db_client.post(
        f"/api/v1/jobs/{first['id']}/postings/{second['postings'][0]['id']}/snapshots",
        json={"raw_jd": "不能写到另一个职位。"},
    )
    assert foreign.status_code == 404


def test_unknown_job_and_stale_update_return_contract_errors(db_client: TestClient) -> None:
    """未找到与并发过期写入必须映射为稳定错误码。"""
    missing = db_client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    job = _create_job(db_client)
    stale = db_client.patch(f"/api/v1/jobs/{job['id']}", json={"version": 99, "title": "过期写入"})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFLICT"


def test_current_jd_returns_to_a_without_rewriting_capture_time(db_client: TestClient) -> None:
    """A→B→A 必须回到旧 A，历史读取不会推进来源当前指向。"""
    original = _create_job(db_client)
    path = f"/api/v1/jobs/{original['id']}"
    save_path = f"{path}/postings/{original['postings'][0]['id']}/snapshots"
    assert db_client.post(save_path, json={"raw_jd": "B 的完整原文"}).status_code == 201
    returned = db_client.post(save_path, json={"raw_jd": _manual_payload()["raw_jd"]}).json()["data"]
    assert returned["id"] == original["latest_snapshot"]["id"]
    assert returned["captured_at"] == original["latest_snapshot"]["captured_at"]
    before = db_client.get(path).json()["data"]
    history = db_client.get(f"{path}/snapshots").json()["data"]
    assert len(history) == 2
    assert db_client.get(path).json()["data"] == before
    assert before["latest_snapshot"]["id"] == returned["id"]
    assert before["postings"][0]["current_snapshot_id"] == returned["id"]
    assert before["postings"][0]["last_seen_at"] > original["postings"][0]["last_seen_at"]


def test_multi_source_current_selection_and_missing_current(db_client: TestClient) -> None:
    """真实隔离会话验证最近接收优先、ID 并列稳定及无当前不兜底历史。"""
    original = _create_job(db_client)
    opportunity_id = uuid.UUID(original["id"])
    original_posting_id = uuid.UUID(original["postings"][0]["id"])
    other_id = uuid.UUID(int=original_posting_id.int + 1)
    moment = datetime(2026, 1, 2, tzinfo=UTC)

    async def arrange() -> str:
        """只使用 db_client 已替换的随机 schema 会话工厂。"""
        async with cast(Any, db_client.app).state.database.session() as session:
            first = await session.get(JobPosting, original_posting_id)
            assert first is not None
            first.last_seen_at = moment
            other = JobPosting(
                id=other_id,
                opportunity_id=opportunity_id,
                source=JobSource.BOSS,
                last_seen_at=moment - timedelta(days=1),
            )
            session.add(other)
            await session.flush()
            saved = JobSnapshot(posting_id=other_id, content_hash=content_hash("另一来源"), raw_jd="另一来源")
            session.add(saved)
            await session.flush()
            other.current_snapshot_id = saved.id
            await session.commit()
            return str(saved.id)

    portal = cast(Any, db_client).portal
    other_snapshot_id = portal.call(arrange)
    path = f"/api/v1/jobs/{opportunity_id}"
    assert db_client.get(path).json()["data"]["latest_snapshot"]["id"] == original["latest_snapshot"]["id"]

    async def adjust(*, missing: bool = False) -> None:
        """推进另一来源时间至并列，或移除两来源当前指向，保留所有历史。"""
        async with cast(Any, db_client.app).state.database.session() as session:
            for posting_id in (original_posting_id, other_id):
                row = await session.get(JobPosting, posting_id)
                assert row is not None
                row.last_seen_at = moment
                if missing:
                    row.current_snapshot_id = None
            await session.commit()

    portal.call(adjust)
    for _ in range(2):
        detail = db_client.get(path).json()["data"]
        assert detail["latest_snapshot"]["id"] == other_snapshot_id
        assert detail["latest_snapshot"]["posting_id"] == str(other_id)
    portal.call(lambda: adjust(missing=True))
    assert db_client.get(path).json()["data"]["latest_snapshot"] is None
    assert db_client.get("/api/v1/jobs").json()["data"][0]["latest_captured_at"] is None
    assert len(db_client.get(f"{path}/snapshots").json()["data"]) == 2
