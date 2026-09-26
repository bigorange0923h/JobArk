"""简历导入的本地解析、AI 候选约束与确认落库测试。"""

import base64
import json
import logging
from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.ai.llm.gateway import TransientAiGatewayError
from app.core.errors import ValidationFailedError
from app.modules.profile.import_service import ResumeUpload, parse_document

API = "/api/v1/profile"
AI_API = "/api/v1/ai"
HTML = (
    "<html><head><title>不应出现</title></head><body>"
    "<h1>张三</h1><p>北京 Python</p>"
    "<p>甲公司 后端工程师 2020 年至 2022 年</p>"
    "<p>订单系统重构 负责人 技术栈 Spring Boot 主导订单链路拆分 性能提升 30% 2021 年至 2022 年</p>"
    "<p>乙大学 计算机科学 学士 2016 年至 2020 年</p>"
    "<script>伪造经历</script></body></html>"
)


def _upload(html: str = HTML) -> dict[str, str]:
    """构造不含真实个人资料的测试上传请求。"""
    return {"filename": "sample.html", "content_base64": base64.b64encode(html.encode()).decode()}


def _candidate() -> dict[str, Any]:
    """构造可逐字定位到测试简历的候选。"""
    return {
        "full_name": "张三",
        "name_quote": "张三",
        "city": "北京",
        "skills": [{"name": "Python", "source_quote": "北京 Python"}],
        "experiences": [
            {
                "company": "甲公司",
                "title": "后端工程师",
                "start_date": "2020-01-01",
                "end_date": "2022-01-01",
                "source_quote": "甲公司 后端工程师 2020 年至 2022 年",
            }
        ],
        "projects": [
            {
                "name": "订单系统重构",
                "role": "负责人",
                "responsibilities": "主导订单链路拆分",
                "achievements": "性能提升 30%",
                "tech_stack": ["Spring Boot"],
                "start_date": "2021-01-01",
                "end_date": "2022-01-01",
                "source_quote": (
                    "订单系统重构 负责人 技术栈 Spring Boot 主导订单链路拆分 性能提升 30% "
                    "2021 年至 2022 年"
                ),
            }
        ],
        "educations": [
            {
                "school": "乙大学",
                "major": "计算机科学",
                "degree": "学士",
                "start_date": "2016-01-01",
                "end_date": "2020-01-01",
                "source_quote": "乙大学 计算机科学 学士 2016 年至 2020 年",
            }
        ],
    }


def _configure_default_model(client: TestClient) -> None:
    """创建服务商与首个模型，使唯一默认模型存在。

    不提交 API Key：这些用例只验证候选约束与确认边界，不需要凭据，
    因此也不依赖 TEST 环境的凭据加密根密钥。
    """
    provider = client.post(
        f"{AI_API}/providers",
        json={"name": "测试服务商", "base_url": "https://example.test/v1"},
    ).json()["data"]
    created = client.post(
        f"{AI_API}/providers/{provider['id']}/models",
        json={"name": "测试模型", "remote_model_id": "test-model"},
    )
    assert created.status_code == 201, created.text


def test_html_parser_ignores_hidden_content() -> None:
    """脚本和标题不会进入送给 AI 的简历文字。"""
    document = parse_document(ResumeUpload(**_upload()))
    assert "张三" in document.text
    assert "伪造经历" not in document.text
    assert "不应出现" not in document.text


@pytest.mark.parametrize("filename", ["sample.txt", "sample.docx", "sample.pdf.exe"])
def test_import_rejects_unsupported_file(filename: str) -> None:
    """只允许 PDF 或 HTML 后缀。"""
    with pytest.raises(ValidationFailedError):
        parse_document(ResumeUpload(filename=filename, content_base64=_upload()["content_base64"]))


def test_import_rejects_scanned_or_empty_pdf() -> None:
    """无文字的 PDF 不会被当作有效候选来源。"""
    with pytest.raises(ValidationFailedError):
        parse_document(ResumeUpload(filename="empty.pdf", content_base64=base64.b64encode(b"%PDF-invalid").decode()))


def test_import_extracts_text_layer_pdf() -> None:
    """有文字层的 PDF 可本地提取，不依赖实际 AI 服务。"""
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        # 测试内构造最小文字层 PDF；pypdf 没有暴露写入任意 PDF 对象的公开 API。
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}  # pyright: ignore[reportPrivateUsage]
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (Resume Text) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)  # pyright: ignore[reportPrivateUsage]
    output = BytesIO()
    writer.write(output)
    document = parse_document(
        ResumeUpload(filename="sample.pdf", content_base64=base64.b64encode(output.getvalue()).decode())
    )
    assert document.text == "Resume Text"


def test_preview_requires_explicit_external_consent(client: TestClient) -> None:
    """未同意时不触发 AI 调用。"""
    response = client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": False})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_import_without_default_model_fails_without_writing(db_client: TestClient) -> None:
    """没有默认模型时给出可理解的冲突错误，且不写入档案。"""
    response = db_client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert "AI 模型配置" in response.json()["error"]["message"]
    assert db_client.get(API).status_code == 404


def test_preview_checks_model_quotes(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """模型捏造的经历只会被排除，不阻塞同一份简历里的其他可验证候选。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """返回故意错误的候选，验证原文校验。"""
        assert task == "extract_profile_from_resume"
        assert "伪造经历" not in input_data["resume_text"]
        candidate = _candidate()
        candidate["experiences"][0]["company"] = "不存在的公司"
        return candidate

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    with caplog.at_level(logging.INFO, logger="app.modules.profile.import_service"):
        response = db_client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})
    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    assert preview["completeness"] == {
        "status": "PARTIAL",
        "valid_item_count": 3,
        "rejected_item_count": 1,
        "unmapped_field_count": 0,
        "excluded_field_count": 0,
    }
    assert preview["candidate"]["experiences"] == []
    assert len(preview["candidate"]["skills"]) == 1
    assert preview["rejected_items"] == [
        {
            "group": "experiences",
            "index": 0,
            "code": "EVIDENCE_INVALID",
            "fields": [],
            "message": "该条目的字段或摘录无法逐字定位到简历原文，未进入待确认列表。",
        }
    ]
    stages = [getattr(record, "stage", None) for record in caplog.records]
    assert "document_parsed" in stages
    assert "model_resolved" in stages
    assert "ai_response_parsed" in stages
    invalid = [
        record for record in caplog.records if getattr(record, "event", None) == "profile_import_candidate_invalid"
    ]
    shapes = [
        record for record in caplog.records if getattr(record, "event", None) == "profile_import_model_output_shape"
    ]
    assert len(invalid) == 1
    assert len(shapes) == 1
    assert vars(invalid[0])["candidate_group"] == "experience"
    assert vars(invalid[0])["candidate_index"] == 0
    shape = vars(shapes[0])["model_output_shape"]
    assert shape["type"] == "object"
    assert shape["fields"]["experiences"]["type"] == "array"
    assert shape["fields"]["experiences"]["items"][0]["fields"]["company"] == {"type": "str"}
    assert "不存在的公司" not in caplog.text
    assert "张三" not in caplog.text


def test_preview_keeps_supported_fields_and_reports_unknown_item_fields(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """项目职责/成果是明确契约字段；其他未知字段可见但不会阻塞项目候选。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        candidate = _candidate()
        candidate["projects"][0]["deliverables"] = "原型与上线文档"
        return candidate

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    response = db_client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})

    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    assert preview["candidate"]["projects"][0]["responsibilities"] == "主导订单链路拆分"
    assert preview["candidate"]["projects"][0]["achievements"] == "性能提升 30%"
    assert preview["completeness"]["status"] == "PARTIAL"
    assert preview["completeness"]["rejected_item_count"] == 0
    assert preview["warnings"] == [
        {
            "group": "projects",
            "index": 0,
            "code": "UNMAPPED_MODEL_FIELD",
            "fields": ["deliverables"],
            "message": "模型返回了当前档案结构未支持的字段；这些字段未作为候选事实导入。",
        }
    ]


def test_preview_keeps_project_when_only_optional_fields_lack_quote(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """项目名称与摘录有效时，模型概括的可选字段被清空而不会拖累整个项目。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        candidate = _candidate()
        candidate["projects"][0]["description"] = "负责订单核心能力建设"
        candidate["projects"][0]["achievements"] = "系统稳定性显著提升"
        candidate["projects"][0]["tech_stack"] = ["Spring Boot", "PostgreSQL"]
        return candidate

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    response = db_client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})

    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    project = preview["candidate"]["projects"][0]
    assert project["name"] == "订单系统重构"
    assert project["responsibilities"] == "主导订单链路拆分"
    assert project["description"] is None
    assert project["achievements"] is None
    assert project["tech_stack"] == ["Spring Boot"]
    assert preview["completeness"] == {
        "status": "PARTIAL",
        "valid_item_count": 4,
        "rejected_item_count": 0,
        "unmapped_field_count": 0,
        "excluded_field_count": 3,
    }
    assert preview["warnings"] == [
        {
            "group": "projects",
            "index": 0,
            "code": "FIELD_NOT_IN_QUOTE",
            "fields": ["description", "achievements", "tech_stack"],
            "message": "这些字段未能在项目原文摘录中逐字定位，未作为简历事实导入；可由本人补充。",
        }
    ]


def test_preview_generates_project_with_name_role_stack_description_and_dates(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """简历中的项目含名称、角色、技术栈、说明与日期时，应生成完整候选项目并可确认写入。

    这是"项目经历无法填充到候选档案"的回归用例：修复前只要项目的可选取值没能全部逐字落在
    同一段摘录里，`_check_sourced_item` 就会把整条项目判为越界并丢弃，用户看到的是项目经历为空。
    """
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """返回带项目说明与日期的候选，参数字段与契约一致。"""
        candidate = _candidate()
        candidate["projects"] = [
            {
                "name": "订单系统重构",
                "role": "负责人",
                "description": "主导订单链路拆分",
                "tech_stack": ["Spring Boot"],
                "start_date": "2021-01-01",
                "end_date": "2022-01-01",
                "source_quote": (
                    "订单系统重构 负责人 技术栈 Spring Boot 主导订单链路拆分 性能提升 30% 2021 年至 2022 年"
                ),
            }
        ]
        return candidate

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    upload = _upload()
    preview = db_client.post(f"{API}/import-preview", json={**upload, "confirm_external": True})

    assert preview.status_code == 200, preview.text
    project = preview.json()["data"]["candidate"]["projects"][0]
    assert project["name"] == "订单系统重构"
    assert project["role"] == "负责人"
    assert project["tech_stack"] == ["Spring Boot"]
    assert project["description"] == "主导订单链路拆分"
    assert project["start_date"] == "2021-01-01"
    assert project["end_date"] == "2022-01-01"
    assert preview.json()["data"]["completeness"]["rejected_item_count"] == 0

    saved = db_client.post(
        f"{API}/import-confirm",
        json={**upload, **preview.json()["data"], "project_indices": [0], "confirmed": True},
    )

    assert saved.status_code == 201, saved.text
    assert saved.json()["data"]["projects_added"] == 1
    saved_project = db_client.get(API).json()["data"]["projects"][0]
    assert saved_project["name"] == "订单系统重构"
    assert saved_project["role"] == "负责人"
    assert saved_project["description"] == "主导订单链路拆分"


def test_preview_keeps_project_skeleton_when_only_name_has_evidence(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只有项目名称有原文证据时，保留项目骨架并把其余可选字段留空，而不是丢弃整条项目。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """返回摘录仅覆盖项目名称的候选，模拟模型未把字段纳入摘录的情况。"""
        candidate = _candidate()
        candidate["projects"] = [
            {
                "name": "订单系统重构",
                "role": "负责人",
                "description": "主导订单链路拆分",
                "tech_stack": ["Spring Boot"],
                "start_date": "2021-01-01",
                "end_date": "2022-01-01",
                "source_quote": "订单系统重构",
            }
        ]
        return candidate

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    response = db_client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})

    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    project = preview["candidate"]["projects"][0]
    assert project["name"] == "订单系统重构"
    # 缺失可选字段留空（None/[]），既不伪造默认值，也不隐藏字段。
    assert project["role"] is None
    assert project["description"] is None
    assert project["tech_stack"] == []
    assert project["start_date"] is None
    assert project["end_date"] is None
    assert preview["completeness"]["rejected_item_count"] == 0
    assert preview["completeness"]["excluded_field_count"] == 5
    assert preview["warnings"][0]["code"] == "FIELD_NOT_IN_QUOTE"
    assert preview["warnings"][0]["fields"] == [
        "role",
        "description",
        "tech_stack",
        "start_date",
        "end_date",
    ]


def test_preview_maps_project_title_alias_and_string_tech_stack(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型沿用工作经历命名（title）或把技术栈写成字符串时，项目仍应进入候选并给出可见提示。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """返回用 `title` 表示项目名、技术栈为分隔字符串的候选。"""
        candidate = _candidate()
        candidate["projects"] = [
            {
                "title": "订单系统重构",
                "role": "负责人",
                "tech_stack": "Spring Boot",
                "description": "主导订单链路拆分",
                "start_date": "2021-01-01",
                "end_date": "2022-01-01",
                "source_quote": (
                    "订单系统重构 负责人 技术栈 Spring Boot 主导订单链路拆分 性能提升 30% 2021 年至 2022 年"
                ),
            }
        ]
        return candidate

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    response = db_client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})

    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    project = preview["candidate"]["projects"][0]
    assert project["name"] == "订单系统重构"
    assert project["tech_stack"] == ["Spring Boot"]
    assert preview["completeness"]["unmapped_field_count"] == 0
    assert preview["warnings"][0] == {
        "group": "projects",
        "index": 0,
        "code": "FIELD_ALIAS_MAPPED",
        "fields": ["title", "tech_stack"],
        "message": "模型使用了与本档案契约等价的字段名或字符串技术栈，已归一化后继续按原文摘录校验。",
    }


def test_preview_rejects_only_schema_invalid_item(db_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """单项字段类型错误不再导致同批有效条目丢失。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        candidate = _candidate()
        candidate["experiences"][0]["start_date"] = "不是日期"
        return candidate

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    response = db_client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})

    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    assert preview["candidate"]["experiences"] == []
    assert preview["rejected_items"][0]["code"] == "SCHEMA_INVALID"
    assert preview["rejected_items"][0]["fields"] == ["start_date"]


def test_preview_retries_one_transient_gateway_failure(db_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """预览不写事实时，明确短暂失败只额外发送一次。"""
    _configure_default_model(db_client)
    attempts = 0

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TransientAiGatewayError("temporary")
        return _candidate()

    async def no_sleep(seconds: float) -> None:
        """避免重试策略测试产生真实等待。"""
        assert seconds == 1.0

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    monkeypatch.setattr("app.modules.profile.import_service.asyncio.sleep", no_sleep)
    response = db_client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})

    assert response.status_code == 200, response.text
    assert attempts == 2


def test_stream_preview_reports_error_without_consent(client: TestClient) -> None:
    """流开始后仍用统一错误包和请求编号报告业务失败。"""
    response = client.post(f"{API}/import-preview-stream", json={**_upload(), "confirm_external": False})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in response.text
    assert "event: error" in response.text
    error_block = response.text.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0]
    error = json.loads(error_block)
    assert error["error"]["code"] == "VALIDATION_ERROR"
    assert error["http_status"] == 422
    assert error["meta"]["request_id"] == response.headers["X-Request-ID"]


def test_preview_and_confirm_import(db_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """预览不写库；人工确认后创建档案及来源明确的四类事实。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """模拟默认模型返回可验证的候选。"""
        return _candidate()

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    upload = _upload()
    preview = db_client.post(f"{API}/import-preview", json={**upload, "confirm_external": True})
    assert preview.status_code == 200, preview.text
    assert db_client.get(API).status_code == 404
    payload = {
        **upload,
        **preview.json()["data"],
        "skill_indices": [0],
        "experience_indices": [0],
        "project_indices": [0],
        "education_indices": [0],
        "confirmed": True,
    }
    denied = db_client.post(f"{API}/import-confirm", json={**payload, "confirmed": False})
    assert denied.status_code == 422
    assert db_client.get(API).status_code == 404
    saved = db_client.post(f"{API}/import-confirm", json=payload)
    assert saved.status_code == 201, saved.text
    assert saved.json()["data"]["created_profile"] is True
    assert saved.json()["data"]["projects_added"] == 1
    profile = db_client.get(API).json()["data"]
    assert profile["full_name"] == "张三"
    assert len(profile["skills"]) == len(profile["experiences"]) == len(profile["educations"]) == 1
    assert len(profile["projects"]) == 1
    assert profile["projects"][0]["name"] == "订单系统重构"
    assert profile["projects"][0]["tech_stack"] == ["Spring Boot"]
    # 项目的职责与成果合并进项目说明：Profile 的项目事实只有 description 一列。
    assert profile["projects"][0]["description"] == "主导订单链路拆分\n性能提升 30%"
    assert profile["skills"][0]["claim_status"] == "UNVERIFIED"
    assert profile["evidences"][0]["verification_status"] == "UNVERIFIED"
    assert profile["evidences"][0]["source_hash"] == preview.json()["data"]["source_hash"]
    repeated = db_client.post(f"{API}/import-confirm", json=payload)
    assert repeated.status_code == 422
    assert len(db_client.get(API).json()["data"]["evidences"]) == 1


def test_stream_preview_reports_real_stages_and_result(db_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """SSE 阶段按处理顺序到达，最终结果仍是原来的候选契约。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """返回有来源的固定候选，不访问真实模型。"""
        return _candidate()

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    response = db_client.post(f"{API}/import-preview-stream", json={**_upload(), "confirm_external": True})
    assert response.status_code == 200
    assert response.text.index('"stage": "document_parsed"') < response.text.index('"stage": "ai_request_started"')
    assert response.text.index('"stage": "ai_response_parsed"') < response.text.index('"stage": "candidate_validated"')
    result_block = response.text.split("event: result\ndata: ", 1)[1].split("\n\n", 1)[0]
    result = json.loads(result_block)
    assert result["success"] is True
    assert result["data"]["candidate"]["full_name"] == "张三"
    assert result["meta"]["request_id"] == response.headers["X-Request-ID"]
    assert db_client.get(API).status_code == 404


def test_confirm_rejects_changed_file(db_client: TestClient) -> None:
    """客户端若在预览后换文件，不能沿用旧候选确认。"""
    payload: dict[str, Any] = {
        **_upload(),
        "source_hash": "0" * 64,
        "candidate": _candidate(),
        "confirmed": True,
    }
    response = db_client.post(f"{API}/import-confirm", json=payload)
    assert response.status_code == 409
    assert db_client.get(API).status_code == 404


def test_import_preserves_existing_profile_and_checks_indices(db_client: TestClient) -> None:
    """已有档案只补充事实，越界选择不得写入。"""
    created = db_client.post(API, json={"full_name": "原有姓名", "city": "上海"})
    assert created.status_code == 201, created.text
    upload = _upload()
    source_hash = parse_document(ResumeUpload(**upload)).source_hash
    payload: dict[str, Any] = {
        **upload,
        "source_hash": source_hash,
        "candidate": _candidate(),
        "skill_indices": [0],
        "experience_indices": [0],
        "education_indices": [0],
        "confirmed": True,
    }
    invalid = db_client.post(f"{API}/import-confirm", json={**payload, "skill_indices": [2]})
    assert invalid.status_code == 422
    out_of_range_project = db_client.post(f"{API}/import-confirm", json={**payload, "project_indices": [1]})
    assert out_of_range_project.status_code == 422
    assert db_client.get(API).json()["data"]["evidences"] == []
    saved = db_client.post(f"{API}/import-confirm", json=payload)
    assert saved.status_code == 201, saved.text
    assert saved.json()["data"]["created_profile"] is False
    profile = db_client.get(API).json()["data"]
    assert profile["full_name"] == "原有姓名"
    assert profile["city"] == "上海"
    assert len(profile["experiences"]) == len(profile["educations"]) == 1


def test_preview_accepts_project_duty_and_achievement_fields(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型按工作经历的习惯给项目带上职责/成果时不得整体失败。

    这是回归用例：项目候选一度只声明了 `description`，`extra="forbid"` 会让
    `projects.0.responsibilities` 触发 extra_forbidden，把整次导入变成 422。
    """
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """返回带职责与成果的项目候选。"""
        return _candidate()

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    response = db_client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})

    assert response.status_code == 200, response.text
    project = response.json()["data"]["candidate"]["projects"][0]
    assert project["responsibilities"] == "主导订单链路拆分"
    assert project["achievements"] == "性能提升 30%"


def test_preview_rejects_fabricated_project(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """项目经历同样受严格校验约束：模型编造的项目不得进入预览。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """返回项目名称被替换成原文中不存在的候选。"""
        candidate = _candidate()
        candidate["projects"][0]["name"] = "不存在的项目"
        return candidate

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    with caplog.at_level(logging.WARNING, logger="app.modules.profile.import_service"):
        response = db_client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})

    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    assert preview["candidate"]["projects"] == []
    assert preview["completeness"]["status"] == "PARTIAL"
    assert preview["rejected_items"][0]["group"] == "projects"
    assert preview["rejected_items"][0]["code"] == "EVIDENCE_INVALID"
    invalid = [
        record for record in caplog.records if getattr(record, "event", None) == "profile_import_candidate_invalid"
    ]
    assert len(invalid) == 1
    assert vars(invalid[0])["candidate_group"] == "project"
    assert vars(invalid[0])["candidate_index"] == 0
    assert "不存在的项目" not in caplog.text


def test_confirm_accepts_edited_candidate_with_manual_evidence(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """用户修正过的条目可以写入，但改挂"本人陈述"证据，未修订条目仍挂简历证据。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """模拟默认模型返回可验证的候选。"""
        return _candidate()

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    upload = _upload()
    preview = db_client.post(f"{API}/import-preview", json={**upload, "confirm_external": True})
    assert preview.status_code == 200, preview.text
    candidate = preview.json()["data"]["candidate"]
    # 用户在预览界面把项目名改成原文摘录之外的说法：允许写入，但来源不再是简历原文。
    candidate["projects"][0]["name"] = "订单系统重构（本人补充命名）"

    saved = db_client.post(
        f"{API}/import-confirm",
        json={
            **upload,
            "source_hash": preview.json()["data"]["source_hash"],
            "candidate": candidate,
            "skill_indices": [0],
            "experience_indices": [0],
            "project_indices": [0],
            "education_indices": [0],
            "confirmed": True,
        },
    )

    assert saved.status_code == 201, saved.text
    profile = db_client.get(API).json()["data"]
    by_source = {evidence["source_type"]: evidence for evidence in profile["evidences"]}
    assert set(by_source) == {"RESUME_DOCUMENT", "MANUAL_DECLARATION"}
    manual = by_source["MANUAL_DECLARATION"]
    resume = by_source["RESUME_DOCUMENT"]
    assert manual["source_hash"] is None
    assert "订单系统重构（本人补充命名）" in manual["content"]
    # 未修订的技能仍挂简历证据，且简历证据里不含被修订后的项目名。
    assert profile["skills"][0]["source_evidence_id"] == resume["id"]
    assert profile["experiences"][0]["source_evidence_id"] == resume["id"]
    assert profile["projects"][0]["source_evidence_id"] == manual["id"]
    assert profile["projects"][0]["name"] == "订单系统重构（本人补充命名）"
    assert "订单系统重构（本人补充命名）" not in resume["content"]


def test_imported_item_can_be_edited_after_import(
    db_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """导入写入的事实可以在档案页继续编辑：这是"采集后允许编辑"的第二段要求。"""
    _configure_default_model(db_client)

    async def fake_generate(
        config: Any, task: str, input_data: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """模拟默认模型返回可验证的候选。"""
        return _candidate()

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    upload = _upload()
    preview = db_client.post(f"{API}/import-preview", json={**upload, "confirm_external": True})
    assert preview.status_code == 200, preview.text
    saved = db_client.post(
        f"{API}/import-confirm",
        json={
            **upload,
            **preview.json()["data"],
            "skill_indices": [0],
            "project_indices": [0],
            "confirmed": True,
        },
    )
    assert saved.status_code == 201, saved.text
    project = db_client.get(API).json()["data"]["projects"][0]

    updated = db_client.patch(
        f"{API}/projects/{project['id']}",
        json={"version": project["version"], "role": "技术负责人", "tech_stack": ["Spring Boot", "MySQL"]},
    )

    assert updated.status_code == 200, updated.text
    payload = updated.json()["data"]
    assert payload["role"] == "技术负责人"
    assert payload["tech_stack"] == ["Spring Boot", "MySQL"]
    # 编辑不会改变来源证据：事实仍然可以追溯到导入时的记录。
    assert payload["source_evidence_id"] == project["source_evidence_id"]


def test_confirm_still_rejects_rewritten_quote(db_client: TestClient) -> None:
    """摘录本身仍必须真实存在于原文：放宽字段值不等于允许编造来源。"""
    upload = _upload()
    candidate = _candidate()
    candidate["projects"][0]["source_quote"] = "原文里没有的摘录"
    payload: dict[str, Any] = {
        **upload,
        "source_hash": parse_document(ResumeUpload(**upload)).source_hash,
        "candidate": candidate,
        "project_indices": [0],
        "confirmed": True,
    }

    response = db_client.post(f"{API}/import-confirm", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert db_client.get(API).status_code == 404
