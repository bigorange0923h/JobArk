"""针对固定输入提供行动提示；选填缺失不等于事实错误或能力缺失。"""

from typing import Any


def data_warnings(profile: dict[str, Any], preference: dict[str, Any]) -> list[str]:
    """返回可操作补充项，不产生分数或阻止用户保存分析。"""
    warnings: list[str] = []
    hard: dict[str, Any] = preference.get("hard_limits") or {}
    if not preference.get("target_roles"):
        warnings.append("请在求职策略填写目标方向；不从头衔或履历猜测职业意愿。")
    if (
        preference.get("salary_min") is not None or preference.get("acceptable_salary_min") is not None
    ) and not hard.get("salary_basis"):
        warnings.append("请在求职策略确认薪资税前/税后口径，否则薪资比较保持未知。")
    projects = profile.get("projects", [])
    if any(not item.get("tech_stack") for item in projects):
        warnings.append("部分项目未填写技术栈；请补充实际使用技术，以便区分技术经验与总工龄。")
    if any(not item.get("experience_id") for item in projects):
        warnings.append("部分项目未关联工作经历；确认属于哪段工作，个人项目可继续留空。")
    if any(not item.get("responsibilities") for item in profile.get("experiences", [])):
        warnings.append("部分工作缺职责描述；请补充本人实际承担内容。")
    if any(not item.get("degree_level") or not item.get("study_mode") for item in profile.get("educations", [])):
        warnings.append("教育层次或学习形式未确认；保留原描述，遇到明确学历要求时请核对。")
    warnings.append("来源摘录仅支持其覆盖的内容；项目详细职责、成果或年限仍需逐项核对，不能虚构指标。")
    return warnings


def fact_evidence(
    fact_id: str, fact: dict[str, Any], quote: str | None, sources: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """展示出处支持程度；摘录存在不代表已经独立核验能力。"""
    source = sources.get(str(fact.get("source_evidence_id"))) or {}
    content = str(source.get("content") or "")
    supported = bool(quote and quote in content and source.get("source_type") != "MANUAL_DECLARATION")
    return {
        "fact_id": fact_id,
        "name": fact.get("name") or fact.get("title") or fact.get("school") or "档案事实",
        "claim_status": fact.get("claim_status", "UNVERIFIED"),
        "fact_quote": quote,
        "evidence_title": source.get("title"),
        "source_support": "EXCERPT_SUPPORTED"
        if supported
        else "SOURCE_ATTACHED"
        if source and source.get("source_type") != "MANUAL_DECLARATION"
        else "SELF_DECLARED",
        "source_verification_status": source.get("verification_status", "UNVERIFIED"),
    }
