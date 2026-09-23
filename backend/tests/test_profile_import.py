"""简历导入的本地解析、AI 候选约束与确认落库测试。"""

import base64
from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.errors import ValidationFailedError
from app.modules.profile.import_service import ResumeUpload, parse_document

API = "/api/v1/profile"
HTML = (
    "<html><head><title>不应出现</title></head><body>"
    "<h1>张三</h1><p>北京 Python</p>"
    "<p>甲公司 后端工程师 2020 年至 2022 年</p>"
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


def test_unconfigured_gateway_fails_without_writing(client: TestClient) -> None:
    """未配置 AI 网关时给出可理解的冲突错误。"""
    response = client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_preview_checks_model_quotes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """模型捏造的经历即使 JSON 形状正确也不能进入预览。"""

    async def fake_generate(task: str, input_data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        """返回故意错误的候选，验证原文校验。"""
        assert task == "extract_profile_from_resume"
        assert "伪造经历" not in input_data["resume_text"]
        candidate = _candidate()
        candidate["experiences"][0]["company"] = "不存在的公司"
        return candidate

    monkeypatch.setattr("app.modules.profile.import_service.gateway.generate", fake_generate)
    response = client.post(f"{API}/import-preview", json={**_upload(), "confirm_external": True})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_preview_and_confirm_import(db_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """预览不写库；人工确认后创建档案及来源明确的三类事实。"""

    async def fake_generate(task: str, input_data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        """模拟现有 AI 网关返回可验证的候选。"""
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
        "education_indices": [0],
        "confirmed": True,
    }
    denied = db_client.post(f"{API}/import-confirm", json={**payload, "confirmed": False})
    assert denied.status_code == 422
    assert db_client.get(API).status_code == 404
    saved = db_client.post(f"{API}/import-confirm", json=payload)
    assert saved.status_code == 201, saved.text
    assert saved.json()["data"]["created_profile"] is True
    profile = db_client.get(API).json()["data"]
    assert profile["full_name"] == "张三"
    assert len(profile["skills"]) == len(profile["experiences"]) == len(profile["educations"]) == 1
    assert profile["skills"][0]["claim_status"] == "UNVERIFIED"
    assert profile["evidences"][0]["verification_status"] == "UNVERIFIED"
    assert profile["evidences"][0]["source_hash"] == preview.json()["data"]["source_hash"]
    repeated = db_client.post(f"{API}/import-confirm", json=payload)
    assert repeated.status_code == 422
    assert len(db_client.get(API).json()["data"]["evidences"]) == 1


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
    assert db_client.get(API).json()["data"]["evidences"] == []
    saved = db_client.post(f"{API}/import-confirm", json=payload)
    assert saved.status_code == 201, saved.text
    assert saved.json()["data"]["created_profile"] is False
    profile = db_client.get(API).json()["data"]
    assert profile["full_name"] == "原有姓名"
    assert profile["city"] == "上海"
    assert len(profile["experiences"]) == len(profile["educations"]) == 1
