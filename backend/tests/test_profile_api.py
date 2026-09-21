"""Profile 领域接口的契约与规则测试。

覆盖正常路径与关键失败路径：单例约束、乐观锁、数据真实性约束（"已验证"必须挂证据）、
引用完整性（被修订引用的事实不可删除）、归档语义，以及修订快照不含联系方式。

未配置 `JOBARK_TEST_DATABASE_URL` 时整组测试会被跳过（见 `conftest.py` 的 `db_client`）。
"""

import json
import uuid
from typing import Any

from fastapi.testclient import TestClient

API = "/api/v1"


def _data(response: Any) -> Any:
    """取出统一响应契约中的 data 字段。

    参数:
        response: 测试客户端返回的响应。

    返回:
        Any: 业务载荷。
    """
    body: dict[str, Any] = response.json()
    assert body["success"] is True, body
    return body["data"]


def _error(response: Any) -> dict[str, Any]:
    """取出统一响应契约中的 error 字段。

    参数:
        response: 测试客户端返回的响应。

    返回:
        dict[str, Any]: 错误对象。
    """
    body: dict[str, Any] = response.json()
    assert body["success"] is False, body
    error: dict[str, Any] = body["error"]
    return error


def _detail_fields(error: dict[str, Any]) -> set[str | None]:
    """收集错误细节中的字段名。

    参数:
        error: 错误对象。

    返回:
        set[str | None]: 出现过的字段名集合。
    """
    details: list[dict[str, Any]] = error["details"]
    return {detail["field"] for detail in details}


def _create_profile(client: TestClient) -> dict[str, Any]:
    """创建档案并返回其内容。

    参数:
        client: 测试客户端。

    返回:
        dict[str, Any]: 档案响应体。
    """
    response = client.post(
        f"{API}/profile",
        json={"full_name": "张伟", "email": "zhang@example.com", "phone": "13800000000", "city": "上海"},
    )
    assert response.status_code == 201, response.text
    return _data(response)


def _create_evidence(client: TestClient) -> dict[str, Any]:
    """创建一条可核验的证据。

    参数:
        client: 测试客户端。

    返回:
        dict[str, Any]: 证据响应体。
    """
    response = client.post(
        f"{API}/profile/evidences",
        json={
            "source_type": "CERTIFICATE",
            "title": "AWS 解决方案架构师认证",
            "source_url": "https://example.com/cert/1",
            "verification_status": "VERIFIED",
        },
    )
    assert response.status_code == 201, response.text
    return _data(response)


def test_profile_is_missing_before_creation(db_client: TestClient) -> None:
    """档案未创建时应返回 404 而不是空对象。"""
    response = db_client.get(f"{API}/profile")

    assert response.status_code == 404
    assert _error(response)["code"] == "RESOURCE_NOT_FOUND"


def test_create_profile_returns_singleton(db_client: TestClient) -> None:
    """创建成功后应返回单例键、初始版本号与空集合。"""
    profile = _create_profile(db_client)

    assert profile["singleton_key"] == "default"
    assert profile["version"] == 1
    assert profile["links"] == []
    assert profile["skills"] == []
    assert profile["preference"] is None


def test_profile_can_only_be_created_once(db_client: TestClient) -> None:
    """V1 只允许一份主档案，重复创建返回 409。"""
    _create_profile(db_client)

    response = db_client.post(f"{API}/profile", json={"full_name": "另一个人"})

    assert response.status_code == 409
    assert _error(response)["code"] == "CONFLICT"


def test_update_profile_requires_current_version(db_client: TestClient) -> None:
    """乐观锁：正确版本可更新并自增，过期版本返回 409 并指出字段。"""
    profile = _create_profile(db_client)

    updated = db_client.patch(f"{API}/profile", json={"version": profile["version"], "city": "北京"})
    assert updated.status_code == 200, updated.text
    assert _data(updated)["version"] == 2
    assert _data(updated)["city"] == "北京"

    stale = db_client.patch(f"{API}/profile", json={"version": profile["version"], "city": "杭州"})

    assert stale.status_code == 409
    error = _error(stale)
    assert error["code"] == "CONFLICT"
    assert "version" in _detail_fields(error)


def test_update_requires_version_field(db_client: TestClient) -> None:
    """局部更新缺少 version 时应在校验层被拒绝，而不是绕过乐观锁。"""
    _create_profile(db_client)

    response = db_client.patch(f"{API}/profile", json={"city": "北京"})

    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_ERROR"


def test_archived_evidence_is_hidden_from_default_list(db_client: TestClient) -> None:
    """归档后的证据默认不再出现，但在 include_archived 下仍可查看。"""
    _create_profile(db_client)
    evidence = _create_evidence(db_client)

    archived = db_client.delete(f"{API}/profile/evidences/{evidence['id']}")
    assert archived.status_code == 200, archived.text
    assert _data(archived)["archived_at"] is not None

    assert _data(db_client.get(f"{API}/profile/evidences")) == []
    listed = _data(db_client.get(f"{API}/profile/evidences", params={"include_archived": True}))
    assert [item["id"] for item in listed] == [evidence["id"]]


def test_verified_skill_requires_evidence(db_client: TestClient) -> None:
    """无证据却标记为 VERIFIED 的技能在请求校验阶段即被拒绝。"""
    _create_profile(db_client)

    response = db_client.post(f"{API}/profile/skills", json={"name": "Python", "claim_status": "VERIFIED"})

    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_ERROR"


def test_skill_rejects_unknown_evidence(db_client: TestClient) -> None:
    """引用不存在的证据返回 422，并指出出错字段。"""
    _create_profile(db_client)

    response = db_client.post(
        f"{API}/profile/skills",
        json={"name": "Python", "source_evidence_id": str(uuid.uuid4()), "claim_status": "VERIFIED"},
    )

    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert "source_evidence_id" in _detail_fields(error)


def test_skill_name_duplicates_are_rejected(db_client: TestClient) -> None:
    """规范化后同名的技能不能重复录入。"""
    _create_profile(db_client)
    evidence = _create_evidence(db_client)
    first = db_client.post(
        f"{API}/profile/skills",
        json={"name": "Python", "source_evidence_id": evidence["id"], "claim_status": "VERIFIED"},
    )
    assert first.status_code == 201, first.text

    duplicate = db_client.post(f"{API}/profile/skills", json={"name": "  python  "})

    assert duplicate.status_code == 409
    error = _error(duplicate)
    assert error["code"] == "CONFLICT"
    assert "name" in _detail_fields(error)


def test_clearing_evidence_while_verified_is_rejected(db_client: TestClient) -> None:
    """更新后状态与证据不匹配时应拒绝：不能通过清空证据绕开"已验证必须挂证据"。"""
    _create_profile(db_client)
    evidence = _create_evidence(db_client)
    skill = _data(
        db_client.post(
            f"{API}/profile/skills",
            json={"name": "Python", "source_evidence_id": evidence["id"], "claim_status": "VERIFIED"},
        )
    )

    response = db_client.patch(
        f"{API}/profile/skills/{skill['id']}",
        json={"version": skill["version"], "source_evidence_id": None},
    )

    assert response.status_code == 422
    assert "source_evidence_id" in _detail_fields(_error(response))


def test_experience_rejects_reversed_dates(db_client: TestClient) -> None:
    """结束日期早于开始日期时返回 422，而不是依赖数据库约束变成 500。"""
    _create_profile(db_client)

    response = db_client.post(
        f"{API}/profile/experiences",
        json={"company": "某公司", "title": "后端工程师", "start_date": "2024-01-01", "end_date": "2023-01-01"},
    )

    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_ERROR"


def test_unknown_skill_returns_not_found(db_client: TestClient) -> None:
    """更新不存在的记录返回 404。"""
    _create_profile(db_client)

    response = db_client.patch(
        f"{API}/profile/skills/{uuid.uuid4()}",
        json={"version": 1, "category": "语言"},
    )

    assert response.status_code == 404
    assert _error(response)["code"] == "RESOURCE_NOT_FOUND"


def test_preference_lifecycle(db_client: TestClient) -> None:
    """偏好：未设置返回 404，首次创建不接受 version，之后必须带当前版本号。"""
    _create_profile(db_client)

    assert db_client.get(f"{API}/profile/preference").status_code == 404

    created = db_client.put(f"{API}/profile/preference", json={"target_locations": ["上海"], "salary_min": 30000})
    assert created.status_code == 200, created.text
    assert _data(created)["version"] == 1

    without_version = db_client.put(f"{API}/profile/preference", json={"target_locations": ["北京"]})
    assert without_version.status_code == 422

    updated = db_client.put(
        f"{API}/profile/preference",
        json={"target_locations": ["北京"], "salary_min": 35000, "version": 1},
    )
    assert updated.status_code == 200, updated.text
    assert _data(updated)["version"] == 2

    stale = db_client.put(f"{API}/profile/preference", json={"target_locations": ["深圳"], "version": 1})
    assert stale.status_code == 409


def test_referenced_skill_cannot_be_deleted(db_client: TestClient) -> None:
    """被资料修订引用的事实不能删除，错误中要给出引用它的修订号。"""
    _create_profile(db_client)
    evidence = _create_evidence(db_client)
    skill = _data(
        db_client.post(
            f"{API}/profile/skills",
            json={"name": "Python", "source_evidence_id": evidence["id"], "claim_status": "VERIFIED"},
        )
    )
    revision = db_client.post(f"{API}/profile/revisions", json={"reason": "生成投递简历"})
    assert revision.status_code == 201, revision.text
    assert _data(revision)["revision_no"] == 1

    response = db_client.delete(f"{API}/profile/skills/{skill['id']}")

    assert response.status_code == 409
    error = _error(response)
    assert error["code"] == "CONFLICT"
    assert "1" in error["details"][0]["reason"]
    # 删除失败后记录必须仍然存在，避免"报错但数据已变"。
    assert [item["id"] for item in _data(db_client.get(f"{API}/profile"))["skills"]] == [skill["id"]]


def test_unreferenced_skill_can_be_deleted(db_client: TestClient) -> None:
    """未被引用的事实可以物理删除。"""
    _create_profile(db_client)
    skill = _data(db_client.post(f"{API}/profile/skills", json={"name": "Go"}))

    response = db_client.delete(f"{API}/profile/skills/{skill['id']}")

    assert response.status_code == 200
    assert _data(response)["id"] == skill["id"]
    assert _data(db_client.get(f"{API}/profile"))["skills"] == []


def test_revision_snapshot_excludes_contact_details(db_client: TestClient) -> None:
    """修订快照不得包含联系方式。

    快照会被后续 LLM 流程读取，而联系方式与匹配、简历生成无关；一旦写入快照，
    就有被带进提示词的风险。
    """
    _create_profile(db_client)
    _create_evidence(db_client)

    revision = db_client.post(f"{API}/profile/revisions", json={"reason": "发起匹配"})
    assert revision.status_code == 201, revision.text

    serialized = json.dumps(_data(revision)["snapshot_json"], ensure_ascii=False)
    assert "zhang@example.com" not in serialized
    assert "13800000000" not in serialized
    assert "AWS 解决方案架构师认证" in serialized
