"""原文提取器：逐行保留要求及出处，不推断原文未给出的条件。"""

import re
from typing import Literal

from pydantic import BaseModel, Field


class Requirement(BaseModel):
    """原文中的一项要求；hard 仅来自明确的强制措辞。"""

    text: str = Field(description="原始条件文字。")
    category: str = Field(description="技能、学历、经验或待人工确认。")
    hard: bool = Field(description="是否含必须/至少等明确强制措辞。")
    source_quote: str = Field(description="JD 内可直接定位的逐字引用。")
    kind: Literal["REQUIREMENT", "RESPONSIBILITY", "BONUS", "BENEFIT"] = Field(
        default="REQUIREMENT", description="条件用途；旧解析缺失时兼容普通要求。"
    )


class JDAnalysis(BaseModel):
    """保守本地提取结果；不是语义模型推断。"""

    parser_version: str = "literal-lines-v2"
    requirements: list[Requirement]
    uncertainties: list[str]


def parse_jd(raw_jd: str) -> JDAnalysis:
    """按行提取显式条件；未识别行保留为未知，不制造学历/年限。"""
    requirements: list[Requirement] = []
    for line in raw_jd.splitlines():
        text = line.strip()
        if not text:
            continue
        category = "UNKNOWN"
        kind: Literal["REQUIREMENT", "RESPONSIBILITY", "BONUS", "BENEFIT"] = "REQUIREMENT"
        if re.search(r"福利|五险|年假|补贴|团建", text):
            kind = "BENEFIT"
        elif re.search(r"加分|优先|preferred|bonus", text, re.I):
            kind = "BONUS"
        elif re.search(r"负责|职责|参与|开发|维护", text):
            kind = "RESPONSIBILITY"
        if re.search(r"薪资|月薪|年薪|salary", text, re.I):
            category = "SALARY"
        elif re.search(r"地点|办公|远程|混合|全职|合同制|remote|onsite", text, re.I):
            category = "LOCATION"
        elif re.search(r"资格|证书|六级|驾照|certificate", text, re.I):
            category = "ADMISSION"
        elif re.search(r"学历|本科|硕士|博士|学士|degree", text, re.I):
            category = "EDUCATION"
        elif re.search(r"经验|年限|years?", text, re.I):
            category = "EXPERIENCE"
        elif re.search(r"技能|熟悉|掌握|精通|Python|Java|SQL|TypeScript", text, re.I):
            category = "SKILL"
        requirements.append(
            Requirement(
                text=text,
                source_quote=text,
                category=category,
                kind=kind,
                hard=bool(re.search(r"必须|至少|必备|must|required", text, re.I))
                and not bool(re.search(r"不要求|无需|非必须|not\s+required", text, re.I)),
            )
        )
    return JDAnalysis(
        requirements=requirements,
        uncertainties=["本地逐行提取未推断隐含条件；职责、福利等非要求文字可能包含在待确认条目中。"],
    )
