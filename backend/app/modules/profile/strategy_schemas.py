"""策略补充结构：偏好保持软语义，硬限制只接受显式声明。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.job.exclusions import ExclusionRule


class PriorityRule(ExclusionRule):
    """优先名单仅支持名称、确认行业和岗位关键词，不解除排除。"""

    @model_validator(mode="after")
    def priority_kind(self) -> PriorityRule:
        """复用规则校验，优先名单不支持公司性质。"""
        if self.kind == "COMPANY_NATURE":
            raise ValueError("优先名单不支持公司性质。")
        return self


class HardLimits(BaseModel):
    """对应偏好值的显式硬门禁；默认全部关闭，薪资税口径必须声明。"""

    model_config = ConfigDict(extra="forbid")
    location: bool = Field(default=False, description="地点是否硬限制。")
    employment_type: bool = Field(default=False, description="雇佣类型是否硬限制。")
    remote: bool = Field(default=False, description="工作方式是否硬限制。")
    salary: bool = Field(default=False, description="最低月薪是否硬限制。")
    salary_basis: Literal["GROSS", "NET"] | None = Field(default=None, description="税前或税后；未知不能比较。")
