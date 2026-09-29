"""头像字段的纯契约测试，不依赖数据库。"""

import base64

import pytest
from pydantic import ValidationError

from app.modules.resume.schemas import ResumeContact


def _data_url(mime: str, content: bytes) -> str:
    """构造测试图片 data URL；不包含真实个人图片。"""
    return f"data:image/{mime};base64,{base64.b64encode(content).decode()}"


def test_resume_contact_accepts_optional_png_photo() -> None:
    """新头像可保存，旧文档缺少头像字段也能读取。"""
    assert ResumeContact(email=None, phone=None).photo_data_url is None
    photo = _data_url("png", b"\x89PNG\r\n\x1a\n" + b"example")
    assert ResumeContact(email=None, phone=None, photo_data_url=photo).photo_data_url == photo


@pytest.mark.parametrize("case", ["svg", "wrong_signature", "oversized"])
def test_resume_contact_rejects_invalid_photo(case: str) -> None:
    """拒绝可执行图片、伪装的文件头和超限内容。"""
    photos = {
        "svg": lambda: _data_url("svg+xml", b"<svg></svg>"),
        "wrong_signature": lambda: _data_url("png", b"not a png"),
        "oversized": lambda: _data_url("jpeg", b"\xff\xd8\xff" + b"x" * (256 * 1024)),
    }
    with pytest.raises(ValidationError):
        ResumeContact(email=None, phone=None, photo_data_url=photos[case]())
