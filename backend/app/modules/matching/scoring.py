"""固定六维参考分：模型不可改权重、门禁或把未知当已知。"""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.errors import ValidationFailedError
from app.modules.job.analysis import JDAnalysis
from app.modules.job.exclusions import EvaluationInput, ExclusionRule, evaluate, normalize_name

SCORING_VERSION = "six-dimensions-v2"
DIMENSIONS = Literal["SKILL", "RESPONSIBILITY", "ADMISSION", "SALARY", "LOCATION", "DIRECTION"]
WEIGHTS: dict[DIMENSIONS, float] = {
    "SKILL": 3.0,
    "RESPONSIBILITY": 2.0,
    "ADMISSION": 1.0,
    "SALARY": 1.5,
    "LOCATION": 1.5,
    "DIRECTION": 1.0,
}

# 与前端 cn-division 2026.0.1 同源的本地省市路径；不从任意地址文本猜城市。
CITY_PATHS: list[list[str]] = json.loads(
    (Path(__file__).parents[1] / "job" / "city_paths.json").read_text(encoding="utf-8")
)


def city_identity(value: str) -> str | None:
    """用明确目录映射城市全称、简称和省市路径；无映射为未知。"""
    clean = normalize_name(value)
    matches = {
        province + city
        for province, city in CITY_PATHS
        if clean in {normalize_name(city), normalize_name(city.removesuffix("市")), normalize_name(province + city)}
    }
    return next(iter(matches)) if len(matches) == 1 else None


def location_ratio(actual: str | None, desired: list[str]) -> float | None:
    """多城市 OR；未确认地区/详细地址不能直接判为不满足。"""
    if not actual or not desired:
        return None
    if any(normalize_name(actual) == normalize_name(value) for value in desired):
        return 1.0
    current = city_identity(actual)
    targets = [city_identity(value) for value in desired]
    if current is None or any(value is None for value in targets):
        return None
    return float(current in targets)


def employment_ratio(actual: str | None, desired: list[str]) -> float | None:
    """只对明确同义的雇佣类型比较；列表外不同值保持待确认。"""
    if not actual or not desired:
        return None
    aliases = {
        "全职": "FULL_TIME",
        "full_time": "FULL_TIME",
        "兼职": "PART_TIME",
        "part_time": "PART_TIME",
        "实习": "INTERNSHIP",
        "internship": "INTERNSHIP",
        "合同制": "CONTRACT",
        "contract": "CONTRACT",
    }
    if any(normalize_name(actual) == normalize_name(value) for value in desired):
        return 1.0
    current = aliases.get(normalize_name(actual))
    targets = [aliases.get(normalize_name(value)) for value in desired]
    if current is None or any(value is None for value in targets):
        return None
    return float(current in targets)


def validate_anchor(value: float | None) -> float | None:
    """只接受有限的五档锚点；其他数值拒绝，不做静默四舍五入。"""
    if value is not None and value not in {0.0, 0.25, 0.5, 0.75, 1.0}:
        raise ValueError("仅支持五档条件锚点。")
    return value


class Condition(BaseModel):
    """后端固定的条件，锚点只比较本条件范围，不证明能力已核实。"""

    model_config = ConfigDict(extra="forbid")
    id: str
    dimension: DIMENSIONS
    text: str
    source_quote: str | None = None
    importance: Literal["REQUIRED", "NORMAL", "BONUS"] = "NORMAL"
    hard: bool = False
    status: Literal["KNOWN", "UNKNOWN", "NOT_APPLICABLE"] = "UNKNOWN"
    ratio: float | None = None
    fact_ids: list[str] = Field(default_factory=list)
    fact_quotes: list[str] = Field(default_factory=list, description="与事实 ID 对齐的判断摘录。")
    relation: Literal["SINGLE", "AND", "OR"] = "SINGLE"
    source_start: int | None = None
    source_end: int | None = None
    explanation: str = "缺少足够资料；未知不等于不满足。"

    @model_validator(mode="after")
    def valid_ratio(self) -> Condition:
        """未知不能携带分数，已知必须使用离散锚点。"""
        if (self.status == "KNOWN") != (self.ratio is not None):
            raise ValueError("条件状态与锚点不一致。")
        validate_anchor(self.ratio)
        return self


class Assessment(BaseModel):
    """模型仅返回条件 ID、事实依据和有限锚点，不能修改条件权重。"""

    model_config = ConfigDict(extra="forbid")
    condition_id: str
    ratio: float | None
    fact_ids: list[str] = Field(max_length=20)
    fact_quotes: list[str] = Field(max_length=20, description="与事实 ID 对齐的逐字摘录。")
    explanation: str = Field(min_length=1, max_length=1500)

    @field_validator("ratio")
    @classmethod
    def anchor(cls, value: float | None) -> float | None:
        """校验模型锚点，不能直接输出任意连续得分。"""
        return validate_anchor(value)


class Assessments(BaseModel):
    """完整协议；遗漏条件保持未知，不因模型失败伪造已知结论。"""

    model_config = ConfigDict(extra="forbid")
    assessments: list[Assessment] = Field(max_length=200)


def fingerprint(value: Any) -> str:
    """对实际相关内容规范序列化，排除无关备注前由调用方构造输入。"""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def facts(profile: dict[str, Any], document: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """取冻结修订中的事实；简历模式只取实际表达的事实，不发送联系方式。"""
    expressed = {
        str(row.get("source_fact_id"))
        for key in ("skills", "experiences", "projects", "educations", "languages")
        for row in (document or {}).get(key, [])
    }
    return {
        str(row["id"]): row
        for key in ("skills", "experiences", "projects", "educations", "languages")
        for row in profile.get(key, [])
        if row.get("id") and (document is None or str(row["id"]) in expressed)
    }


def profile_inputs(profile: dict[str, Any]) -> dict[str, Any]:
    """冻结参与判断的事实和关联来源内容；来源修改也应提示历史过期。"""
    return {"facts": facts(profile), "evidences": profile.get("evidences", [])}


def conditions(parsed: JDAnalysis) -> list[Condition]:
    """从明确解析生成固定条件；福利不评分，重复同维摘录仅计算一次。"""
    rows: list[Condition] = []
    seen: set[tuple[str, str]] = set()
    for item in parsed.requirements:
        if item.kind == "BENEFIT" or item.category in {"SALARY", "LOCATION"}:
            continue
        dimension: DIMENSIONS = (
            "ADMISSION"
            if item.category in {"EDUCATION", "EXPERIENCE", "ADMISSION"}
            else "RESPONSIBILITY"
            if item.kind == "RESPONSIBILITY"
            else "SKILL"
            if item.category == "SKILL"
            else "RESPONSIBILITY"
        )
        identity = (dimension, normalize_name(item.source_quote))
        if identity in seen:
            continue
        seen.add(identity)
        rows.append(
            Condition(
                id=f"c{len(rows)}",
                dimension=dimension,
                text=item.text,
                source_quote=item.source_quote,
                importance="REQUIRED" if item.hard else "BONUS" if item.kind == "BONUS" else "NORMAL",
                hard=item.hard,
                relation=item.relation,
                source_start=item.source_start,
                source_end=item.source_end,
            )
        )
    for dimension in WEIGHTS:
        if not any(row.dimension == dimension for row in rows):
            rows.append(
                Condition(
                    id=f"c{len(rows)}",
                    dimension=dimension,
                    text=f"{dimension} 信息",
                    status="NOT_APPLICABLE"
                    if dimension == "ADMISSION" and parsed.admission_status == "NONE"
                    else "UNKNOWN",
                    explanation="原文明确无准入要求。"
                    if dimension == "ADMISSION" and parsed.admission_status == "NONE"
                    else "JD 或策略信息缺失；解析未识别不等于明确不存在。",
                )
            )
    return rows


def apply_assessments(
    rows: list[Condition], output: Assessments, frozen_facts: dict[str, dict[str, Any]]
) -> list[Condition]:
    """逐项校验固定条件与修订事实出处；策略条件不得由模型覆写。"""
    by_id = {row.id: row for row in rows}
    updates: dict[str, Assessment] = {}
    for item in output.assessments:
        row = by_id.get(item.condition_id)
        if (
            row is None
            or item.condition_id in updates
            or row.dimension in {"SALARY", "LOCATION", "DIRECTION"}
            or row.status == "NOT_APPLICABLE"
        ):
            raise ValidationFailedError("模型条件引用无效，原始输入已保留。")
        if len(item.fact_ids) != len(item.fact_quotes) or any(fact_id not in frozen_facts for fact_id in item.fact_ids):
            raise ValidationFailedError("模型引用不属于所选资料修订。")
        for fact_id, quote in zip(item.fact_ids, item.fact_quotes, strict=True):
            content = {
                key: value
                for key, value in frozen_facts[fact_id].items()
                if key not in {"id", "source_evidence_id", "claim_status", "category", "experience_id"}
            }
            fact_text = "\n".join(str(value) for value in content.values() if value is not None)
            if not quote.strip() or quote not in fact_text:
                raise ValidationFailedError("模型事实摘录无法核对。")
        if item.ratio is not None and not item.fact_ids:
            raise ValidationFailedError("模型已知结论缺少事实依据。")
        if (
            item.ratio is not None
            and item.ratio > 0.25
            and all(
                set(frozen_facts[id])
                <= {
                    "id",
                    "name",
                    "category",
                    "claim_status",
                    "source_evidence_id",
                    "proficiency",
                    "years_of_experience",
                }
                for id in item.fact_ids
            )
        ):
            # 技能记录无法独立证明职责、熟练度或年限；仅名称对应最多支持相关背景。
            item = item.model_copy(update={"ratio": 0.25})
        if row.relation == "OR":
            # 本轮没有实现组内替代项的独立证明，不能把整体低分当作硬冲突。
            item = item.model_copy(update={"ratio": None, "explanation": "替代条件需逐项核对，当前保持未知。"})
        updates[item.condition_id] = item
    return [
        row.model_copy(
            update={
                "ratio": updates[row.id].ratio,
                "status": "KNOWN" if updates[row.id].ratio is not None else "UNKNOWN",
                "fact_ids": updates[row.id].fact_ids,
                "fact_quotes": updates[row.id].fact_quotes,
                "explanation": updates[row.id].explanation,
            }
        )
        if row.id in updates
        else row
        for row in rows
    ]


def strategy_conditions(
    rows: list[Condition], strategy: dict[str, Any], job: dict[str, Any], jd: str
) -> tuple[list[Condition], list[str], list[str]]:
    """比较明确口径的策略，不从正文猜城市、薪资或远程；缺值保持未知。"""
    preference: dict[str, Any] = strategy.get("preference") or {}
    hard: dict[str, Any] = preference.get("hard_limits") or {}
    conflicts: list[str] = []
    unknowns: list[str] = []
    checks: list[tuple[DIMENSIONS, str, float | None, bool]] = []
    for name, key, actual in (
        ("location", "target_locations", job.get("location")),
        ("employment_type", "job_types", job.get("employment_type")),
        ("remote", "remote_preference", job.get("remote_mode")),
    ):
        desired = preference.get(key)
        options: list[Any] = (
            cast(list[Any], desired) if isinstance(desired, list) else [desired] if desired and desired != "ANY" else []
        )
        ratio = (
            float(any(normalize_name(str(actual)) == normalize_name(str(value)) for value in options))
            if actual and options
            else None
        )
        if name == "location":
            ratio = location_ratio(str(actual) if actual else None, [str(value) for value in options])
        if name == "employment_type":
            ratio = employment_ratio(str(actual) if actual else None, [str(value) for value in options])
        checks.append(("LOCATION", name, ratio, bool(hard.get(name))))
    salary: dict[str, Any] = job.get("salary") or {}
    target = preference.get("salary_min")
    floor = preference.get("acceptable_salary_min")
    # 原硬限制以 salary_min 为底线；新增独立底线为空时保留原行为，不改写旧偏好。
    if floor is None and hard.get("salary"):
        floor = target
    comparable = (
        salary.get("currency") == preference.get("salary_currency")
        and bool(preference.get("salary_currency"))
        and salary.get("period") == "MONTH"
        and bool(salary.get("basis"))
        and salary.get("basis") == hard.get("salary_basis")
    )
    low, high = salary.get("min"), salary.get("max")
    floor_ratio = None
    if comparable and floor is not None:
        if high is not None and high < floor:
            floor_ratio = 0.0
        elif low is not None and low >= floor:
            floor_ratio = 1.0
    ratio = None
    if comparable and target is not None:
        if low is not None and low >= target:
            ratio = 1.0
        elif high is not None and high < target:
            ratio = 0.5 if floor_ratio == 1 else 0.0 if floor is None or floor_ratio == 0 else None
    checks.append(("SALARY", "salary", ratio, False))
    if hard.get("salary"):
        checks.append(("SALARY", "salary_floor", floor_ratio, True))
    roles: list[str] = preference.get("target_roles") or []
    keywords: list[str] = preference.get("role_keywords") or []
    title = str(job.get("title") or "")

    def matching_terms(terms: list[str], content: str) -> list[str]:
        """复用边界与否定处理，只保留确定的字面方向线索。"""
        return [
            term
            for i, term in enumerate(terms)
            if evaluate(
                [ExclusionRule(id=f"r{i}", kind="JD_KEYWORD", value=term)],
                EvaluationInput(
                    company_name="", nature_code=None, industry_code=None, outsourcing_arrangement=None, raw_jd=content
                ),
            ).verdict
            == "EXCLUDED"
        ]

    title_hits = matching_terms(roles, title)
    body_hits = matching_terms(roles, jd)
    keyword_hits = matching_terms(keywords, jd)
    direction = 0.75 if title_hits else 0.5 if body_hits else 0.25 if roles and keyword_hits else None
    checks.append(("DIRECTION", "target_roles", direction, False))
    retained = [row for row in rows if row.dimension not in {"LOCATION", "SALARY", "DIRECTION"}]
    for dimension, name, ratio, is_hard in checks:
        if is_hard and ratio == 0:
            conflicts.append(f"硬限制不满足：{name}")
        if is_hard and ratio is None:
            unknowns.append(f"硬限制待确认：{name}")
        not_applicable = name == "remote" and preference.get("remote_preference") == "ANY"
        retained.append(
            Condition(
                id=f"strategy-{name}",
                dimension=dimension,
                text={
                    "location": "目标地点",
                    "employment_type": "雇佣类型",
                    "remote": "工作方式",
                    "salary": "期望月薪区间",
                    "salary_floor": "最低可接受月薪",
                    "target_roles": "职业方向",
                }[name],
                hard=is_hard,
                status="NOT_APPLICABLE" if not_applicable else "KNOWN" if ratio is not None else "UNKNOWN",
                ratio=ratio,
                explanation=(
                    f"职位标题方向线索：{', '.join(title_hits)}；仍需核对具体职责。"
                    if name == "target_roles" and title_hits
                    else f"JD 方向线索：{', '.join(body_hits)}；不能证明完整方向适合。"
                    if name == "target_roles" and body_hits
                    else f"仅补充关键词线索：{', '.join(keyword_hits)}。"
                    if name == "target_roles" and roles and keyword_hits
                    else "达到最低可接受月薪，低于期望区间。"
                    if name == "salary" and ratio == 0.5
                    else "同口径月薪达到期望下限；高于期望上界不扣分。"
                    if name == "salary" and ratio == 1
                    else "同口径月薪低于期望下限；这是软偏好比较，不自动排除。"
                    if name == "salary" and ratio == 0
                    else "依据已保存字段与当次策略比较。"
                    if ratio is not None
                    else "缺少同口径或已确认信息；区间跨底线也需确认。"
                )
                + (
                    f" 期望月薪区间：{target}–{preference.get('salary_max') or '未设上界'}。"
                    if name == "salary"
                    else ""
                ),
            )
        )
    return retained, conflicts, unknowns


def score(rows: list[Condition], excluded: bool = False, review: bool = False) -> dict[str, Any]:
    """计算原始上下界与覆盖率；不适用移除，未知仍保留其权重。"""
    applicable = [row for row in rows if row.status != "NOT_APPLICABLE"]
    active: set[DIMENSIONS] = {row.dimension for row in applicable}
    total = sum(WEIGHTS[key] for key in active)
    lower = unknown = known = 0.0
    details: list[dict[str, Any]] = []
    priorities = {"REQUIRED": 2.0, "NORMAL": 1.0, "BONUS": 0.5}
    for row in applicable:
        within = sum(priorities[item.importance] for item in applicable if item.dimension == row.dimension)
        weight = WEIGHTS[row.dimension] / total * 10 * priorities[row.importance] / within
        if row.ratio is None:
            unknown += weight
        else:
            known += weight
            lower += weight * row.ratio
        details.append({**row.model_dump(), "weight": weight})
    coverage = known / 10
    hard_unknown = any(row.hard and (row.status == "UNKNOWN" or row.ratio not in (0, 1)) for row in applicable)
    hard_conflict = any(row.hard and row.ratio == 0 for row in applicable)
    single = coverage >= 0.8 - 1e-9 and not hard_unknown and bool(applicable)
    recommendation = (
        "不建议投递"
        if excluded or hard_conflict
        else "先补充/确认信息"
        if review or hard_unknown or not single
        else "优先准备投递"
        if lower >= 8
        else "可以考虑"
        if lower >= 6
        else "当前优先级较低"
    )
    return {
        "version": SCORING_VERSION,
        "lower": lower,
        "upper": min(10, lower + unknown) if applicable else 10.0,
        "coverage": coverage,
        "single_score": lower if single else None,
        "conditions": details,
        "recommendation": recommendation,
        "boundary": "产品参考阈值，不是录用概率；未验证事实不等于独立核实。",
    }
