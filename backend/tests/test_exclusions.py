"""排除规则的纯判定边界；不依赖外部模型或数据库。"""

import pytest

from app.modules.job.exclusions import EvaluationInput, ExclusionRule, evaluate


def source(**changes: str | None) -> EvaluationInput:
    """构造已确认的非外包岗位，按用例覆盖字段。"""
    data = {
        "company_name": "甲科技",
        "nature_code": "OTHER",
        "industry_code": "TECH/SOFTWARE",
        "outsourcing_arrangement": "DIRECT",
        "raw_jd": "负责 Python 开发。",
    }
    return EvaluationInput(**(data | changes))  # type: ignore[arg-type]


def rule(kind: str, value: str, enabled: bool = True) -> ExclusionRule:
    """以稳定 ID 创建一条有效规则。"""
    return ExclusionRule(id="test", kind=kind, value=value, enabled=enabled)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "value", "changes"),
    [
        ("COMPANY_NATURE", "OUTSOURCING_RELATED", {"nature_code": "LABOR_DISPATCH"}),
        ("COMPANY_INDUSTRY", "TECH", {}),
        ("COMPANY_NAME", " 甲科技 ", {}),
        ("JD_KEYWORD", "Python", {}),
        ("JD_KEYWORD", "负责", {}),
    ],
)
def test_four_types_match(kind: str, value: str, changes: dict[str, str]) -> None:
    """四维字面命中及中文短语均能排除。"""
    assert evaluate([rule(kind, value)], source(**changes)).verdict == "EXCLUDED"


def test_only_one_outsourcing_job_is_excluded() -> None:
    """同公司的直招岗位不能因为另一岗位外包而一起排除。"""
    condition = rule("COMPANY_NATURE", "OUTSOURCING_RELATED")
    assert evaluate([condition], source(outsourcing_arrangement="OUTSOURCING")).verdict == "EXCLUDED"
    assert evaluate([condition], source()).verdict == "ELIGIBLE"
    assert evaluate([condition], source(outsourcing_arrangement=None)).verdict == "REVIEW"


def test_industry_parent_child_and_legacy_text() -> None:
    """只认目录中明确的父子关系；历史文本不会被猜测为代码。"""
    assert evaluate([rule("COMPANY_INDUSTRY", "TECH")], source()).verdict == "EXCLUDED"
    assert evaluate([rule("COMPANY_INDUSTRY", "TECH/HARDWARE")], source()).verdict == "ELIGIBLE"
    assert evaluate([rule("COMPANY_INDUSTRY", "TECH")], source(industry_code=None)).verdict == "REVIEW"


def test_names_are_exact_and_aliases_explicit() -> None:
    """完整同名都命中，简称和别名需独立规则。"""
    assert evaluate([rule("COMPANY_NAME", "甲科技")], source(company_name=" 甲科技 ")).verdict == "EXCLUDED"
    assert evaluate([rule("COMPANY_NAME", "甲")], source()).verdict == "ELIGIBLE"


def test_keyword_boundaries_and_negation() -> None:
    """英文不匹配词中片段；否定上下文只升级待核对。"""
    assert evaluate([rule("JD_KEYWORD", "java")], source(raw_jd="JavaScript")).verdict == "ELIGIBLE"
    assert evaluate([rule("JD_KEYWORD", "外包")], source(raw_jd="非外包岗位")).verdict == "REVIEW"
    assert evaluate([rule("JD_KEYWORD", "外包")], source(raw_jd="外包项目岗位")).verdict == "EXCLUDED"


def test_excluded_precedes_review_and_disabled_rule_does_not_apply() -> None:
    """确定命中优先于未知；停用规则不参与计算。"""
    rules = [rule("COMPANY_INDUSTRY", "FINANCE"), rule("COMPANY_NAME", "甲科技")]
    assert evaluate(rules, source(industry_code=None)).verdict == "EXCLUDED"
    assert evaluate([rule("COMPANY_NAME", "甲科技", False)], source()).verdict == "ELIGIBLE"


def test_unrecognized_persisted_classification_is_review() -> None:
    """即使数据库遇到旧值或非法代码，也不能把未知误判为可考虑。"""
    assert evaluate([rule("COMPANY_INDUSTRY", "TECH")], source(industry_code="旧代码")).verdict == "REVIEW"
    assert evaluate([rule("COMPANY_NATURE", "OUTSOURCING_RELATED")], source(nature_code="旧代码")).verdict == "REVIEW"
