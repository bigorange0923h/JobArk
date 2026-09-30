"""四类求职排除规则的纯判定；不从候选文本猜测公司分类。"""

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RuleKind = Literal["COMPANY_NATURE", "COMPANY_INDUSTRY", "COMPANY_NAME", "JD_KEYWORD"]
Verdict = Literal["EXCLUDED", "REVIEW", "ELIGIBLE"]

# 仅显式目录定义父子关系；历史 industry 自由文本不参与映射。
INDUSTRIES: dict[str, tuple[str, ...]] = {
    "TECH": ("TECH/SOFTWARE", "TECH/HARDWARE", "TECH/INTERNET"),
    "FINANCE": ("FINANCE/BANKING", "FINANCE/INSURANCE", "FINANCE/SECURITIES"),
    "MANUFACTURING": ("MANUFACTURING/ELECTRONICS", "MANUFACTURING/OTHER"),
    "SERVICES": ("SERVICES/HR", "SERVICES/CONSULTING"),
}
NATURES = {"OUTSOURCING_PROVIDER", "LABOR_DISPATCH", "OUTSOURCING_RELATED"}


class ExclusionRule(BaseModel):
    """单条用户维护的规则；ID 在编辑和启停后保持稳定。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    kind: RuleKind
    value: str = Field(min_length=1, max_length=200)
    enabled: bool = True

    @field_validator("value")
    @classmethod
    def valid_text(cls, value: str) -> str:
        """防止零宽字符和控制字符制造肉眼不可见的规则。"""
        if any(unicodedata.category(char).startswith("C") for char in value):
            raise ValueError("规则不得包含控制或不可见字符。")
        return value

    @model_validator(mode="after")
    def valid_code(self) -> ExclusionRule:
        """封闭代码必须来自明确目录，不允许靠名称推测类别。"""
        if self.kind == "COMPANY_NATURE" and self.value not in NATURES:
            raise ValueError("未知公司性质代码。")
        if (
            self.kind == "COMPANY_INDUSTRY"
            and self.value not in INDUSTRIES
            and not any(self.value in children for children in INDUSTRIES.values())
        ):
            raise ValueError("未知行业代码。")
        return self


class EvaluationInput(BaseModel):
    """已落库输入的评估视图；空分类代表未知，绝不代表不命中。"""

    company_name: str
    nature_code: str | None
    industry_code: str | None
    outsourcing_arrangement: str | None
    raw_jd: str


class ExclusionReason(BaseModel):
    """命中或待核对依据，snippet 保存 JD 原文片段。"""

    kind: str
    rule_id: str | None = None
    text: str
    snippet: str | None = None


class Decision(BaseModel):
    """排除决定及其依据。"""

    verdict: Verdict
    reasons: list[ExclusionReason]


def normalize_name(value: str) -> str:
    """公司名称作完整、全半角与大小写规范化；不推断别名或法人身份。"""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _keyword_hits(text: str, keyword: str) -> list[tuple[str, bool]]:
    """返回原文片段与局部否定提示；局部提示只负责升级待核对。"""
    term = keyword
    body = text
    ascii_word = all(char.isascii() and (char.isalnum() or char == "_") for char in term)
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])" if ascii_word else re.escape(term)
    found: list[tuple[str, bool]] = []
    for match in re.finditer(pattern, body, re.IGNORECASE):
        start, end = match.span()
        snippet = text[max(0, start - 24) : min(len(text), end + 24)]
        prefix = body[max(0, start - 8) : start].casefold()
        uncertain = bool(re.search(r"(?:非|不是|并非|无需|不属于|非[\s\S]{0,3}|not\s+|no\s+)$", prefix))
        found.append((snippet, uncertain))
    return found


def evaluate(rules: list[ExclusionRule], source: EvaluationInput) -> Decision:
    """确定性求值：确定排除优先于任何未知或含糊。"""
    excluded: list[ExclusionReason] = []
    review: list[ExclusionReason] = []
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.kind == "COMPANY_NAME":
            if not source.company_name.strip():
                review.append(ExclusionReason(kind=rule.kind, rule_id=rule.id, text="公司名称缺失"))
            elif normalize_name(rule.value) == normalize_name(source.company_name):
                excluded.append(
                    ExclusionReason(kind=rule.kind, rule_id=rule.id, text=f"公司名称完整命中：{source.company_name}")
                )
        elif rule.kind == "COMPANY_NATURE":
            if rule.value == "OUTSOURCING_RELATED":
                if source.nature_code in NATURES - {"OUTSOURCING_RELATED"} or source.outsourcing_arrangement in {
                    "OUTSOURCING",
                    "ONSITE",
                }:
                    excluded.append(
                        ExclusionReason(kind=rule.kind, rule_id=rule.id, text="已确认公司性质或当前岗位安排为外包相关")
                    )
                elif source.nature_code not in {"OTHER", "OUTSOURCING_PROVIDER", "LABOR_DISPATCH"} or (
                    source.outsourcing_arrangement not in {"DIRECT", "OUTSOURCING", "ONSITE"}
                ):
                    review.append(
                        ExclusionReason(kind=rule.kind, rule_id=rule.id, text="公司性质或当前岗位安排尚未确认")
                    )
            elif source.nature_code not in {"OTHER", "OUTSOURCING_PROVIDER", "LABOR_DISPATCH"}:
                review.append(ExclusionReason(kind=rule.kind, rule_id=rule.id, text="公司性质尚未确认"))
            elif source.nature_code == rule.value:
                excluded.append(ExclusionReason(kind=rule.kind, rule_id=rule.id, text=f"公司性质命中：{rule.value}"))
        elif rule.kind == "COMPANY_INDUSTRY":
            if source.industry_code is None or (
                source.industry_code not in INDUSTRIES
                and not any(source.industry_code in children for children in INDUSTRIES.values())
            ):
                review.append(ExclusionReason(kind=rule.kind, rule_id=rule.id, text="公司行业尚未确认"))
            elif source.industry_code == rule.value or source.industry_code in (INDUSTRIES.get(rule.value) or ()):
                excluded.append(
                    ExclusionReason(kind=rule.kind, rule_id=rule.id, text=f"已确认行业命中：{source.industry_code}")
                )
        else:
            hits = _keyword_hits(source.raw_jd, rule.value)
            if not source.raw_jd.strip():
                review.append(ExclusionReason(kind=rule.kind, rule_id=rule.id, text="JD 原文缺失"))
            for snippet, uncertain in hits:
                reason = ExclusionReason(
                    kind=rule.kind,
                    rule_id=rule.id,
                    text="否定或含糊语境，需核对" if uncertain else "JD 字面命中",
                    snippet=snippet,
                )
                (review if uncertain else excluded).append(reason)
    return Decision(verdict="EXCLUDED" if excluded else "REVIEW" if review else "ELIGIBLE", reasons=excluded + review)
