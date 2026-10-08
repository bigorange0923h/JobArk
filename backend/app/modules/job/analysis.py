"""保守条件提取：保留原文位置，不把替代条件或解析遗漏视为通过。"""

import re
from typing import Literal

from pydantic import BaseModel, Field

PARSER_VERSION = "literal-conditions-v3"


def validate_source(analysis: JDAnalysis, raw: str) -> None:
    """校验新旧解析出处；位置成对且精确，模型不能凭遗漏声明无准入。"""
    for item in analysis.requirements:
        if not item.source_quote.strip() or item.source_quote not in raw or item.text != item.source_quote:
            raise ValueError("条件缺少原文依据。")
        if (item.source_start is not None or item.source_end is not None) and (
            item.source_start is None
            or item.source_end is None
            or raw[item.source_start : item.source_end] != item.source_quote
        ):
            raise ValueError("条件原文位置无效。")
        if item.hard and (
            item.relation == "OR"
            or re.search(r"不要求|无需|非必须|不限|not\s+required", item.source_quote, re.I)
            or not re.search(r"必须|至少|必备|及以上|以上学历|must|required", item.source_quote, re.I)
        ):
            raise ValueError("硬条件缺少独立强制依据。")
    if analysis.admission_status == "NONE" and (
        not re.search(r"(?:无|没有|不设)准入要求", raw)
        or any(item.category in {"ADMISSION", "EDUCATION", "EXPERIENCE"} for item in analysis.requirements)
    ):
        raise ValueError("原文未明确证明无准入。")


class Requirement(BaseModel):
    """独立条件或不可安全拆分的替代组；旧解析允许缺位置元数据。"""

    text: str = Field(description="逐字条件文字。")
    category: str = Field(description="技能、学历、经验、准入或未知。")
    hard: bool = Field(description="明确强制条件；否定和替代组不自动设硬门禁。")
    source_quote: str = Field(description="当次 JD 中可定位的连续摘录。")
    kind: Literal["REQUIREMENT", "RESPONSIBILITY", "BONUS", "BENEFIT"] = "REQUIREMENT"
    source_start: int | None = Field(default=None, ge=0, description="原文起始字符偏移。")
    source_end: int | None = Field(default=None, ge=0, description="原文结束字符偏移，不含该位置。")
    relation: Literal["SINGLE", "AND", "OR"] = Field(default="SINGLE", description="并列条件或整体替代组。")
    group_id: str | None = Field(default=None, description="同一原文行的条件组标识。")
    experience_subject: str | None = Field(default=None, description="明确经验对象的原文；不从总工龄推算技术工龄。")


class JDAnalysis(BaseModel):
    """提取结果；UNKNOWN 表示没有足够信息证明不存在准入。"""

    parser_version: str = PARSER_VERSION
    requirements: list[Requirement] = Field(description="条件集合，遗漏项仍需核对。")
    uncertainties: list[str]
    admission_status: Literal["UNKNOWN", "PRESENT", "NONE"] = Field(
        default="UNKNOWN", description="明确准入存在、明确无准入或未知。"
    )


def parse_jd(raw_jd: str) -> JDAnalysis:
    """拆分安全并列分句并保留偏移；OR 整体留待核对，标题不参与评分。"""
    requirements: list[Requirement] = []
    explicit_none = False
    section = "REQUIREMENT"
    offset = 0
    for line_index, line in enumerate(raw_jd.splitlines(keepends=True)):
        stripped = line.strip()
        header = re.sub(r"^[\d一二三四五六七八九十、.．)）\s]+", "", stripped).rstrip(":：")
        if header in {"岗位职责", "工作职责", "职责", "任职要求", "岗位要求", "职位要求", "福利待遇", "福利"}:
            section = "RESPONSIBILITY" if "职责" in header else "BENEFIT" if "福利" in header else "REQUIREMENT"
            offset += len(line)
            continue
        if re.fullmatch(r"(?:无|没有|不设)准入要求[。.!！]?", stripped):
            explicit_none = True
            offset += len(line)
            continue
        alternative = bool(re.search(r"或者|或|任选|至少一种|任一|\bor\b", stripped, re.I))
        pieces = (
            list(re.finditer(r"[^，,；;。\r\n]+", line)) if not alternative else list(re.finditer(r"[^\r\n]+", line))
        )
        for piece in pieces:
            segment = piece.group()
            prefix = re.match(r"\s*(?:\d+[、.．)）]\s*)?", segment)
            start = piece.start() + (prefix.end() if prefix else 0)
            end = piece.end()
            while end > start and line[end - 1].isspace():
                end -= 1
            quote = line[start:end]
            if not quote:
                continue
            category = "UNKNOWN"
            if re.search(r"薪资|月薪|年薪|salary", quote, re.I):
                category = "SALARY"
            elif re.search(r"地点|办公|远程|混合|全职|合同制|remote|onsite", quote, re.I):
                category = "LOCATION"
            elif re.search(r"资格|证书|六级|驾照|certificate", quote, re.I):
                category = "ADMISSION"
            elif re.search(r"学历|本科|硕士|博士|学士|大专|degree", quote, re.I):
                category = "EDUCATION"
            elif re.search(r"经验|年限|\d+\s*年|years?", quote, re.I):
                category = "EXPERIENCE"
            elif re.search(r"技能|熟悉|掌握|精通|Python|Java|SQL|TypeScript|Docker|Git|RAG|Agent", quote, re.I):
                category = "SKILL"
            kind: Literal["REQUIREMENT", "RESPONSIBILITY", "BONUS", "BENEFIT"] = "REQUIREMENT"
            if section == "BENEFIT" or re.search(r"福利|五险|年假|补贴|团建", quote):
                kind = "BENEFIT"
            elif re.search(r"加分|优先|preferred|bonus", quote, re.I):
                kind = "BONUS"
            elif category not in {"EDUCATION", "EXPERIENCE", "ADMISSION"} and (
                section == "RESPONSIBILITY" or re.search(r"负责|参与|维护", quote)
            ):
                kind = "RESPONSIBILITY"
            hard = bool(re.search(r"必须|至少|必备|及以上|以上学历|must|required", quote, re.I))
            hard = (
                hard
                and kind != "BONUS"
                and not alternative
                and not bool(re.search(r"不要求|无需|非必须|不限|not\s+required", quote, re.I))
            )
            subject = re.search(r"Python|Java(?:Script)?|TypeScript|RAG|Agent|AI|软件开发|后端|前端|工作", quote, re.I)
            requirements.append(
                Requirement(
                    text=quote,
                    source_quote=quote,
                    category=category,
                    kind=kind,
                    hard=hard,
                    source_start=offset + start,
                    source_end=offset + end,
                    relation="OR" if alternative else "AND" if len(pieces) > 1 else "SINGLE",
                    group_id=f"line-{line_index}",
                    experience_subject=subject.group() if category == "EXPERIENCE" and subject else None,
                )
            )
        offset += len(line)
    admission = any(row.category in {"EDUCATION", "EXPERIENCE", "ADMISSION"} for row in requirements)
    return JDAnalysis(
        requirements=requirements,
        admission_status="PRESENT" if admission else "NONE" if explicit_none else "UNKNOWN",
        uncertainties=["本地仅拆分显式分句；替代关系、跨句经验对象及未识别准入要求需人工核对。"],
    )
