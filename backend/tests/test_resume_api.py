"""Resume 领域的契约与规则测试。

覆盖的重点不是"接口能返回 200"，而是几个一旦失效就会造成数据问题的约束：

- 版本不可变：不存在修改或删除版本的入口，因此历史投递引用的版本不会被改写。
- 确认才生效：候选稿在确认前不影响任何正式版本；同一候选稿只能确认一次，
  且重复确认不会留下第二份版本。
- 归档语义：归档的简历方向不能再产生新版本或候选稿。
- 文档结构：模块顺序、显隐配置与结构版本非法时返回 422，而不是把坏数据写进库。

未配置 `JOBARK_TEST_DATABASE_URL` 时整组测试会被跳过（见 `conftest.py` 的 `db_client`）。
"""

import uuid
from typing import Any

from fastapi.testclient import TestClient

API = "/api/v1"

# 一份最小的合法文档：只含必填字段，用于让各用例聚焦在它真正要验证的差异上。
_BASE_DOCUMENT: dict[str, Any] = {
    "basics": {"full_name": "张伟", "headline": "后端工程师", "city": "上海", "links": []},
    "contact": {"email": "zhang@example.com", "phone": "13800000000"},
    "summary": {"text": "5 年后端开发经验。"},
    "experiences": [
        {
            "company": "某公司",
            "title": "后端工程师",
            "start_date": "2022-03-01",
            "highlights": ["负责订单系统重构"],
        }
    ],
    "section_order": ["SUMMARY", "EXPERIENCES", "PROJECTS", "SKILLS", "EDUCATIONS", "LANGUAGES"],
}


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


def _document(**overrides: Any) -> dict[str, Any]:
    """构造文档请求体。

    参数:
        **overrides: 需要覆盖的顶层字段。

    返回:
        dict[str, Any]: 文档请求体。
    """
    document = dict(_BASE_DOCUMENT)
    document.update(overrides)
    return document


def _ensure_profile(client: TestClient) -> None:
    """确保个人档案存在。

    参数:
        client: 测试客户端。

    注意:
        事实与修订都挂在档案之下，因此"先建事实、再建修订"的用例必须先建档案；
        档案已存在时创建返回 409，对调用方而言同样表示"档案可用"。
    """
    profile = client.post(f"{API}/profile", json={"full_name": "张伟", "email": "zhang@example.com"})
    assert profile.status_code in {201, 409}, profile.text


def _create_revision(client: TestClient) -> dict[str, Any]:
    """确保存在档案并创建一份资料修订。

    参数:
        client: 测试客户端。

    返回:
        dict[str, Any]: 修订响应体。

    注意:
        简历版本必须指向修订，因此每个涉及版本的用例都需要这一步。
    """
    _ensure_profile(client)

    revision = client.post(f"{API}/profile/revisions", json={"reason": "生成简历"})
    assert revision.status_code == 201, revision.text
    return _data(revision)


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
            "verification_status": "VERIFIED",
        },
    )
    assert response.status_code == 201, response.text
    return _data(response)


def _create_resume(client: TestClient, name: str = "Java 后端") -> dict[str, Any]:
    """创建一份简历方向。

    参数:
        client: 测试客户端。
        name: 简历方向名称。

    返回:
        dict[str, Any]: 简历方向响应体。
    """
    response = client.post(f"{API}/resumes", json={"name": name, "target_direction": "后端"})
    assert response.status_code == 201, response.text
    return _data(response)


def _create_version(
    client: TestClient,
    resume_id: str,
    revision_id: str,
    *,
    document: dict[str, Any] | None = None,
    evidence_ids: list[str] | None = None,
    reason: str = "首次创建",
) -> Any:
    """创建一个简历版本。

    参数:
        client: 测试客户端。
        resume_id: 简历主键。
        revision_id: 资料修订主键。
        document: 完整文档；默认用最小合法文档。
        evidence_ids: 关联证据。
        reason: 创建原因。

    返回:
        Any: 测试客户端返回的响应。
    """
    return client.post(
        f"{API}/resumes/{resume_id}/versions",
        json={
            "profile_revision_id": revision_id,
            "document": document if document is not None else _document(),
            "created_reason": reason,
            "evidence_ids": evidence_ids or [],
        },
    )


def _create_skill(client: TestClient, name: str = "Python") -> dict[str, Any]:
    """创建一条技能事实。

    参数:
        client: 测试客户端。
        name: 技能名。

    返回:
        dict[str, Any]: 技能响应体。

    注意:
        事实的主键由服务端生成，而"文档能否引用它"取决于它是否落在目标修订的快照里，
        因此用例需要拿到真实主键而不是自己编一个。
    """
    _ensure_profile(client)
    response = client.post(f"{API}/profile/skills", json={"name": name, "category": "编程语言"})
    assert response.status_code == 201, response.text
    return _data(response)


def _create_draft(client: TestClient, resume_id: str, **overrides: Any) -> dict[str, Any]:
    """创建一份候选稿。

    参数:
        client: 测试客户端。
        resume_id: 简历主键。
        **overrides: 需要覆盖的请求体字段。

    返回:
        dict[str, Any]: 候选稿响应体。
    """
    payload: dict[str, Any] = {"document": _document()}
    payload.update(overrides)
    response = client.post(f"{API}/resumes/{resume_id}/drafts", json=payload)
    assert response.status_code == 201, response.text
    return _data(response)


# --------------------------------------------------------------------------------------------
# 简历方向
# --------------------------------------------------------------------------------------------


def test_resume_can_be_created_and_read(db_client: TestClient) -> None:
    """创建后可按主键读回，初始状态为 ACTIVE 且版本号为 1。"""
    resume = _create_resume(db_client)

    fetched = db_client.get(f"{API}/resumes/{resume['id']}")

    assert fetched.status_code == 200, fetched.text
    assert _data(fetched)["name"] == "Java 后端"
    assert resume["status"] == "ACTIVE"
    assert resume["version"] == 1


def test_unknown_resume_returns_not_found(db_client: TestClient) -> None:
    """读取不存在的简历方向返回 404。"""
    response = db_client.get(f"{API}/resumes/{uuid.uuid4()}")

    assert response.status_code == 404
    assert _error(response)["code"] == "RESOURCE_NOT_FOUND"


def test_resume_update_requires_current_version(db_client: TestClient) -> None:
    """乐观锁：正确版本可更新并自增，过期版本返回 409。"""
    resume = _create_resume(db_client)

    updated = db_client.patch(f"{API}/resumes/{resume['id']}", json={"version": 1, "name": "Java 后端（英文）"})
    assert updated.status_code == 200, updated.text
    assert _data(updated)["version"] == 2

    stale = db_client.patch(f"{API}/resumes/{resume['id']}", json={"version": 1, "name": "改名失败"})

    assert stale.status_code == 409
    assert "version" in _detail_fields(_error(stale))


def test_archive_hides_resume_from_default_list(db_client: TestClient) -> None:
    """归档后的简历方向默认不再出现，但仍可在 include_archived 下查看，且不能重复归档。"""
    resume = _create_resume(db_client)

    archived = db_client.delete(f"{API}/resumes/{resume['id']}")
    assert archived.status_code == 200, archived.text
    assert _data(archived)["status"] == "ARCHIVED"

    assert _data(db_client.get(f"{API}/resumes")) == []
    listed = _data(db_client.get(f"{API}/resumes", params={"include_archived": True}))
    assert [item["id"] for item in listed] == [resume["id"]]

    again = db_client.delete(f"{API}/resumes/{resume['id']}")
    assert again.status_code == 409


def test_archived_resume_rejects_new_versions_and_drafts(db_client: TestClient) -> None:
    """归档的含义是方向已停用，继续为它生成版本或候选稿应返回 409。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)
    db_client.delete(f"{API}/resumes/{resume['id']}")

    version = _create_version(db_client, resume["id"], revision["id"])
    draft = db_client.post(f"{API}/resumes/{resume['id']}/drafts", json={"document": _document()})

    assert version.status_code == 409
    assert draft.status_code == 409


# --------------------------------------------------------------------------------------------
# 简历版本
# --------------------------------------------------------------------------------------------


def test_version_requires_existing_profile_revision(db_client: TestClient) -> None:
    """指向不存在的资料修订时返回 422，并指出 profile_revision_id。"""
    client = db_client
    client.post(f"{API}/profile", json={"full_name": "张伟"})
    resume = _create_resume(client)

    response = _create_version(client, resume["id"], str(uuid.uuid4()))

    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert "profile_revision_id" in _detail_fields(error)


def test_versions_increment_and_store_document(db_client: TestClient) -> None:
    """版本号在同简历内自增，文档按提交内容原样保存，结构版本取自文档自身。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)

    first = _create_version(db_client, resume["id"], revision["id"])
    second = _create_version(db_client, resume["id"], revision["id"], reason="针对职位定制")

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert _data(first)["version_no"] == 1
    assert _data(second)["version_no"] == 2
    assert _data(first)["render_schema_version"] == 1
    assert _data(first)["document_json"]["basics"]["full_name"] == "张伟"
    assert _data(first)["document_json"]["contact"]["email"] == "zhang@example.com"


def test_version_cannot_be_modified_or_deleted(db_client: TestClient) -> None:
    """版本不可变：不存在修改或删除入口，因此历史投递引用的版本不会被改写。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)
    version = _data(_create_version(db_client, resume["id"], revision["id"]))

    patched = db_client.patch(f"{API}/resume-versions/{version['id']}", json={"created_reason": "篡改"})
    deleted = db_client.delete(f"{API}/resume-versions/{version['id']}")

    assert patched.status_code == 405
    assert deleted.status_code == 405
    assert _error(patched)["code"] == "METHOD_NOT_ALLOWED"
    stored = db_client.get(f"{API}/resume-versions/{version['id']}")
    assert _data(stored)["created_reason"] == "首次创建"


def test_version_evidence_links_are_deduplicated(db_client: TestClient) -> None:
    """重复提交同一证据会被合并，而不是撞上关联表的唯一约束。"""
    revision = _create_revision(db_client)
    evidence = _create_evidence(db_client)
    resume = _create_resume(db_client)

    response = _create_version(db_client, resume["id"], revision["id"], evidence_ids=[evidence["id"], evidence["id"]])

    assert response.status_code == 201, response.text
    assert _data(response)["evidence_ids"] == [evidence["id"]]


def test_version_rejects_unknown_and_archived_evidences(db_client: TestClient) -> None:
    """不存在与已归档的证据都返回 422，并说明是哪一项不可用。"""
    revision = _create_revision(db_client)
    archived = _create_evidence(db_client)
    db_client.delete(f"{API}/profile/evidences/{archived['id']}")
    resume = _create_resume(db_client)

    unknown = _create_version(db_client, resume["id"], revision["id"], evidence_ids=[str(uuid.uuid4())])
    using_archived = _create_version(db_client, resume["id"], revision["id"], evidence_ids=[archived["id"]])

    assert unknown.status_code == 422
    assert "不存在" in _error(unknown)["details"][0]["reason"]
    assert using_archived.status_code == 422
    assert "已归档" in _error(using_archived)["details"][0]["reason"]


def test_document_section_configuration_is_validated(db_client: TestClient) -> None:
    """模块顺序与显隐配置非法时返回 422，不允许含糊的结构写进库。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)

    def _post(section_order: list[str] | None = None, hidden_sections: list[str] | None = None) -> Any:
        """按给定模块配置提交版本。"""
        document = _document()
        if section_order is not None:
            document["section_order"] = section_order
        if hidden_sections is not None:
            document["hidden_sections"] = hidden_sections
        return db_client.post(
            f"{API}/resumes/{resume['id']}/versions",
            json={
                "profile_revision_id": revision["id"],
                "document": document,
                "created_reason": "非法模块配置",
            },
        )

    missing_section = _post(section_order=["SUMMARY", "EXPERIENCES"])
    duplicated_section = _post(section_order=["SUMMARY", "SUMMARY", "PROJECTS", "SKILLS", "EDUCATIONS", "LANGUAGES"])
    duplicated_hidden = _post(hidden_sections=["SKILLS", "SKILLS"])

    assert missing_section.status_code == 422
    assert duplicated_section.status_code == 422
    assert duplicated_hidden.status_code == 422


def test_document_schema_version_is_fixed(db_client: TestClient) -> None:
    """未知的文档结构版本被拒绝，避免用当前规则误读未来结构。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)

    response = db_client.post(
        f"{API}/resumes/{resume['id']}/versions",
        json={
            "profile_revision_id": revision["id"],
            "document": _document(schema_version=2),
            "created_reason": "未知结构版本",
        },
    )

    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------------------------
# 候选稿
# --------------------------------------------------------------------------------------------


def test_confirmed_draft_creates_new_version(db_client: TestClient) -> None:
    """确认候选稿会新建版本并回写候选稿状态，正式版本只多不改。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)
    existing = _data(_create_version(db_client, resume["id"], revision["id"]))
    draft = _create_draft(db_client, resume["id"], base_resume_version_id=existing["id"])

    confirmed = db_client.post(
        f"{API}/resumes/{resume['id']}/drafts/{draft['id']}/confirm",
        json={"version": draft["version"], "profile_revision_id": revision["id"], "created_reason": "确认候选稿"},
    )

    assert confirmed.status_code == 201, confirmed.text
    version = _data(confirmed)
    assert version["version_no"] == 2
    assert version["document_json"] == draft["document_json"]

    drafts = _data(db_client.get(f"{API}/resumes/{resume['id']}/drafts"))
    assert drafts[0]["status"] == "CONFIRMED"
    assert drafts[0]["confirmed_resume_version_id"] == version["id"]
    # 原有版本保持不变。
    assert _data(db_client.get(f"{API}/resume-versions/{existing['id']}"))["created_reason"] == "首次创建"


def test_confirming_draft_twice_creates_no_second_version(db_client: TestClient) -> None:
    """重复确认返回 409，且不会留下第二份版本。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)
    draft = _create_draft(db_client, resume["id"])
    first = db_client.post(
        f"{API}/resumes/{resume['id']}/drafts/{draft['id']}/confirm",
        json={"version": draft["version"], "profile_revision_id": revision["id"]},
    )
    assert first.status_code == 201, first.text

    again = db_client.post(
        f"{API}/resumes/{resume['id']}/drafts/{draft['id']}/confirm",
        json={"version": draft["version"], "profile_revision_id": revision["id"]},
    )

    assert again.status_code == 409
    assert "status" in _detail_fields(_error(again))
    assert len(_data(db_client.get(f"{API}/resumes/{resume['id']}/versions"))) == 1


def test_confirm_with_stale_version_creates_no_version(db_client: TestClient) -> None:
    """乐观锁版本过期时确认失败，并且不会留下一份"报错但已生效"的版本。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)
    draft = _create_draft(db_client, resume["id"])

    response = db_client.post(
        f"{API}/resumes/{resume['id']}/drafts/{draft['id']}/confirm",
        json={"version": 99, "profile_revision_id": revision["id"]},
    )

    assert response.status_code == 409
    assert _data(db_client.get(f"{API}/resumes/{resume['id']}/versions")) == []
    assert _data(db_client.get(f"{API}/resumes/{resume['id']}/drafts"))[0]["status"] == "DRAFT"


def test_discarded_draft_cannot_be_confirmed(db_client: TestClient) -> None:
    """已丢弃的候选稿不能再确认，也不会产生版本。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)
    draft = _create_draft(db_client, resume["id"])

    discarded = db_client.post(
        f"{API}/resumes/{resume['id']}/drafts/{draft['id']}/discard",
        json={"version": draft["version"]},
    )
    assert discarded.status_code == 200, discarded.text
    assert _data(discarded)["status"] == "DISCARDED"

    confirmed = db_client.post(
        f"{API}/resumes/{resume['id']}/drafts/{draft['id']}/confirm",
        json={"version": draft["version"], "profile_revision_id": revision["id"]},
    )

    assert confirmed.status_code == 409
    assert _data(db_client.get(f"{API}/resumes/{resume['id']}/versions")) == []


def test_draft_base_version_must_belong_to_same_resume(db_client: TestClient) -> None:
    """基线版本属于另一份简历时返回 422，避免把不同方向的表达混在一起。"""
    revision = _create_revision(db_client)
    other = _create_resume(db_client, name="AI 应用")
    foreign_version = _data(_create_version(db_client, other["id"], revision["id"]))
    resume = _create_resume(db_client, name="Java 后端")

    response = db_client.post(
        f"{API}/resumes/{resume['id']}/drafts",
        json={"document": _document(), "base_resume_version_id": foreign_version["id"]},
    )

    assert response.status_code == 422
    assert "base_resume_version_id" in _detail_fields(_error(response))


def test_drafts_are_scoped_to_their_resume(db_client: TestClient) -> None:
    """候选稿只在其所属简历下可见与可操作，跨简历访问按不存在处理。"""
    first = _create_resume(db_client, name="Java 后端")
    second = _create_resume(db_client, name="AI 应用")
    draft = _create_draft(db_client, first["id"])

    assert _data(db_client.get(f"{API}/resumes/{second['id']}/drafts")) == []
    cross = db_client.post(
        f"{API}/resumes/{second['id']}/drafts/{draft['id']}/discard",
        json={"version": draft["version"]},
    )

    assert cross.status_code == 404
    assert _data(db_client.get(f"{API}/resumes/{first['id']}/drafts"))[0]["status"] == "DRAFT"


# --------------------------------------------------------------------------------------------
# 候选稿的确认前编辑
# --------------------------------------------------------------------------------------------


def _draft_by_id(client: TestClient, resume_id: str, draft_id: str) -> dict[str, Any]:
    """按主键取候选稿。

    参数:
        client: 测试客户端。
        resume_id: 简历主键。
        draft_id: 候选稿主键。

    返回:
        dict[str, Any]: 候选稿响应体。

    注意:
        断言"已处理的候选稿不能再编辑"时必须提交它**当前**的版本号，
        否则用旧版本号也会得到 409，测试就分不清拒绝是因为状态还是因为版本过期。
    """
    drafts = _data(client.get(f"{API}/resumes/{resume_id}/drafts"))
    return next(item for item in drafts if item["id"] == draft_id)


def _edit_draft(
    client: TestClient,
    resume_id: str,
    draft_id: str,
    *,
    version: int,
    document: dict[str, Any] | None = None,
) -> Any:
    """提交候选稿编辑请求。

    参数:
        client: 测试客户端。
        resume_id: 简历主键。
        draft_id: 候选稿主键。
        version: 提交的乐观锁版本号。
        document: 完整文档；默认用最小合法文档。

    返回:
        Any: 测试客户端返回的响应。
    """
    return client.patch(
        f"{API}/resumes/{resume_id}/drafts/{draft_id}",
        json={"version": version, "document": document if document is not None else _document()},
    )


def test_draft_can_be_edited_before_confirmation(db_client: TestClient) -> None:
    """待确认的候选稿可以就地修改，版本号随之自增，且不产生正式版本。"""
    resume = _create_resume(db_client)
    draft = _create_draft(db_client, resume["id"])

    response = _edit_draft(
        db_client,
        resume["id"],
        draft["id"],
        version=draft["version"],
        document=_document(summary={"text": "改写后的简介。"}),
    )

    assert response.status_code == 200, response.text
    edited = _data(response)
    assert edited["document_json"]["summary"]["text"] == "改写后的简介。"
    assert edited["version"] == draft["version"] + 1
    assert edited["status"] == "DRAFT"
    # 编辑候选稿不产生正式版本：确认才是唯一的产出路径。
    assert _data(db_client.get(f"{API}/resumes/{resume['id']}/versions")) == []


def test_draft_edit_does_not_touch_confirmed_versions(db_client: TestClient) -> None:
    """编辑候选稿不影响已存在的正式版本，历史内容保持原样。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)
    version = _data(_create_version(db_client, resume["id"], revision["id"]))
    draft = _create_draft(db_client, resume["id"])

    edited = _edit_draft(
        db_client,
        resume["id"],
        draft["id"],
        version=draft["version"],
        document=_document(summary={"text": "候选稿里的新写法。"}),
    )

    assert edited.status_code == 200, edited.text
    stored = _data(db_client.get(f"{API}/resume-versions/{version['id']}"))
    assert stored["document_json"]["summary"]["text"] == "5 年后端开发经验。"


def test_draft_edit_with_stale_version_is_rejected(db_client: TestClient) -> None:
    """乐观锁过期时拒绝保存，库中内容保持原样。"""
    resume = _create_resume(db_client)
    draft = _create_draft(db_client, resume["id"])
    first = _edit_draft(
        db_client,
        resume["id"],
        draft["id"],
        version=draft["version"],
        document=_document(summary={"text": "第一次修改。"}),
    )
    assert first.status_code == 200, first.text

    stale = _edit_draft(
        db_client,
        resume["id"],
        draft["id"],
        version=draft["version"],
        document=_document(summary={"text": "基于旧版本的写入。"}),
    )

    assert stale.status_code == 409
    assert "version" in _detail_fields(_error(stale))
    assert _draft_by_id(db_client, resume["id"], draft["id"])["document_json"]["summary"]["text"] == "第一次修改。"


def test_processed_draft_cannot_be_edited(db_client: TestClient) -> None:
    """已确认或已丢弃的候选稿不能再修改：它们已经是历史决定。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)

    confirmed = _create_draft(db_client, resume["id"])
    db_client.post(
        f"{API}/resumes/{resume['id']}/drafts/{confirmed['id']}/confirm",
        json={"version": confirmed["version"], "profile_revision_id": revision["id"]},
    )
    discarded = _create_draft(db_client, resume["id"])
    db_client.post(
        f"{API}/resumes/{resume['id']}/drafts/{discarded['id']}/discard",
        json={"version": discarded["version"]},
    )

    confirmed_edit = _edit_draft(
        db_client,
        resume["id"],
        confirmed["id"],
        version=_draft_by_id(db_client, resume["id"], confirmed["id"])["version"],
        document=_document(summary={"text": "确认后的追加修改。"}),
    )
    discarded_edit = _edit_draft(
        db_client,
        resume["id"],
        discarded["id"],
        version=_draft_by_id(db_client, resume["id"], discarded["id"])["version"],
        document=_document(summary={"text": "丢弃后的追加修改。"}),
    )

    assert confirmed_edit.status_code == 409
    assert "status" in _detail_fields(_error(confirmed_edit))
    assert discarded_edit.status_code == 409
    assert "status" in _detail_fields(_error(discarded_edit))


def test_draft_edit_rejects_invalid_document(db_client: TestClient) -> None:
    """文档结构非法时返回 422，并且不写入任何内容。"""
    resume = _create_resume(db_client)
    draft = _create_draft(db_client, resume["id"])

    response = _edit_draft(
        db_client,
        resume["id"],
        draft["id"],
        version=draft["version"],
        document=_document(section_order=["SUMMARY", "SUMMARY", "PROJECTS", "SKILLS", "EDUCATIONS", "LANGUAGES"]),
    )

    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_ERROR"
    assert _draft_by_id(db_client, resume["id"], draft["id"])["version"] == draft["version"]


def test_draft_of_another_resume_is_not_found(db_client: TestClient) -> None:
    """跨简历编辑按不存在处理，不暴露另一份简历的候选稿。"""
    first = _create_resume(db_client, name="Java 后端")
    second = _create_resume(db_client, name="AI 应用")
    draft = _create_draft(db_client, first["id"])

    response = _edit_draft(db_client, second["id"], draft["id"], version=draft["version"])

    assert response.status_code == 404


def test_archived_resume_rejects_draft_edit(db_client: TestClient) -> None:
    """归档表示方向已停用，其候选稿也不能再修改。"""
    resume = _create_resume(db_client)
    draft = _create_draft(db_client, resume["id"])
    db_client.delete(f"{API}/resumes/{resume['id']}")

    response = _edit_draft(db_client, resume["id"], draft["id"], version=draft["version"])

    assert response.status_code == 409


# --------------------------------------------------------------------------------------------
# 事实溯源校验
# --------------------------------------------------------------------------------------------


def test_version_rejects_facts_absent_from_revision(db_client: TestClient) -> None:
    """文档引用的事实必须真实存在于所指向的修订中；不存在的引用逐条报出并拒绝创建版本。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)
    invented_skill = str(uuid.uuid4())
    invented_experience = str(uuid.uuid4())

    response = _create_version(
        db_client,
        resume["id"],
        revision["id"],
        document=_document(
            skills=[{"name": "Kubernetes", "source_fact_id": invented_skill}],
            experiences=[
                {
                    "company": "某公司",
                    "title": "后端工程师",
                    "source_fact_id": invented_experience,
                    "highlights": ["负责订单系统重构"],
                }
            ],
        ),
    )

    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert {"skills.0.source_fact_id", "experiences.0.source_fact_id"} <= _detail_fields(error)
    assert _data(db_client.get(f"{API}/resumes/{resume['id']}/versions")) == []


def test_version_accepts_fact_present_in_revision(db_client: TestClient) -> None:
    """引用该修订快照中确实存在的事实时可以创建版本。"""
    skill = _create_skill(db_client, name="Python")
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)

    response = _create_version(
        db_client,
        resume["id"],
        revision["id"],
        document=_document(skills=[{"name": "Python", "source_fact_id": skill["id"]}]),
    )

    assert response.status_code == 201, response.text
    assert _data(response)["document_json"]["skills"][0]["source_fact_id"] == skill["id"]


def test_version_rejects_fact_created_after_revision(db_client: TestClient) -> None:
    """修订是时点快照：修订之后才加入的事实不在其中，不能作为该版本的溯源依据。"""
    revision = _create_revision(db_client)
    later_skill = _create_skill(db_client, name="Rust")
    resume = _create_resume(db_client)

    response = _create_version(
        db_client,
        resume["id"],
        revision["id"],
        document=_document(skills=[{"name": "Rust", "source_fact_id": later_skill["id"]}]),
    )

    assert response.status_code == 422
    assert "skills.0.source_fact_id" in _detail_fields(_error(response))


def test_summary_may_reference_the_profile_itself(db_client: TestClient) -> None:
    """简介的依据可以是档案本身：档案主键也出现在修订快照中，因此是合法溯源。"""
    revision = _create_revision(db_client)
    profile = _data(db_client.get(f"{API}/profile"))
    resume = _create_resume(db_client)

    response = _create_version(
        db_client,
        resume["id"],
        revision["id"],
        document=_document(summary={"text": "5 年后端开发经验。", "source_fact_id": profile["id"]}),
    )

    assert response.status_code == 201, response.text


def test_draft_saves_untraceable_fact_but_confirm_rejects_it(db_client: TestClient) -> None:
    """候选稿允许保存尚未溯源的条目（它是可变的工作状态），确认成版本时才必须可溯源。"""
    revision = _create_revision(db_client)
    resume = _create_resume(db_client)
    invented = str(uuid.uuid4())

    draft = _create_draft(
        db_client,
        resume["id"],
        document=_document(skills=[{"name": "Kubernetes", "source_fact_id": invented}]),
    )
    confirmed = db_client.post(
        f"{API}/resumes/{resume['id']}/drafts/{draft['id']}/confirm",
        json={"version": draft["version"], "profile_revision_id": revision["id"]},
    )

    assert confirmed.status_code == 422
    assert "skills.0.source_fact_id" in _detail_fields(_error(confirmed))
    assert _draft_by_id(db_client, resume["id"], draft["id"])["status"] == "DRAFT"
    assert _data(db_client.get(f"{API}/resumes/{resume['id']}/versions")) == []


# --------------------------------------------------------------------------------------------
# 按主键读取候选稿
# --------------------------------------------------------------------------------------------


def test_draft_can_be_read_by_id(db_client: TestClient) -> None:
    """候选稿可按主键直接读取：编辑器只需要这一份内容，不必拉整张列表再筛。"""
    resume = _create_resume(db_client)
    draft = _create_draft(db_client, resume["id"])

    response = db_client.get(f"{API}/resumes/{resume['id']}/drafts/{draft['id']}")

    assert response.status_code == 200, response.text
    body = _data(response)
    assert body["id"] == draft["id"]
    assert body["document_json"] == draft["document_json"]
    assert body["version"] == draft["version"]
    assert body["status"] == "DRAFT"


def test_draft_of_another_resume_is_not_readable(db_client: TestClient) -> None:
    """跨简历读取按不存在处理，不泄露另一份简历的候选稿内容。"""
    first = _create_resume(db_client, name="Java 后端")
    second = _create_resume(db_client, name="AI 应用")
    draft = _create_draft(db_client, first["id"])

    response = db_client.get(f"{API}/resumes/{second['id']}/drafts/{draft['id']}")

    assert response.status_code == 404
    assert _error(response)["code"] == "RESOURCE_NOT_FOUND"
