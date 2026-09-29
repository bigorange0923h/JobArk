"""技能分类建议只针对无歧义的完整名称。"""

import pytest

from app.modules.profile.import_fixture import FIXTURE_TEXT, mock_extract_profile
from app.modules.profile.import_service import _parse_preview_candidate
from app.modules.profile.skill_categories import suggest_skill_category


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (" Python ", "编程语言"),
        ("PostgreSQL", "数据库"),
        ("Spring Boot", "后端开发"),
        ("Vue", "前端开发"),
        ("LangChain", "AI 应用"),
        ("Redis", None),
        ("自研工作流引擎", None),
        ("Python / Java", None),
    ],
)
def test_suggest_skill_category(name: str, expected: str | None) -> None:
    """模糊技能不猜，明确技能不依赖额外模型调用。"""
    assert suggest_skill_category(name) == expected


def test_preview_suggests_categories_without_using_model_category() -> None:
    """模型只能提取原文技能名；分类由服务端建议，不借原文摘录背书。"""
    output = mock_extract_profile()
    output["skills"][0]["category"] = "其他"
    candidate, _, _, _ = _parse_preview_candidate(output, FIXTURE_TEXT)
    assert [(item.name, item.category, item.origin) for item in candidate.skills] == [
        ("Python", "编程语言", "RESUME"),
        ("PostgreSQL", "数据库", "RESUME"),
    ]
