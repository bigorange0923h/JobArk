"""临时开发夹具：用内置样例简历与固定抽取结果替代真实大模型调用。

用途:
    在本地联调"上传简历 → 抽取 → 候选填充 → 确认写入"整条链路时，不必配置服务商与模型，
    也不消耗模型额度。开启方式见 `Settings.profile_import_fixture`（环境变量
    `JOBARK_PROFILE_IMPORT_FIXTURE`），仅 local/test 生效。

设计:
    固定抽取结果与内置样例文本是**互相自洽**的：每条 `source_quote` 都逐字出现在
    `FIXTURE_TEXT` 里，字段取值也都在各自摘录内。因此夹具只替换"外部输入"，
    候选仍要经过与真实抽取完全相同的 Schema 与原文校验，不放宽任何检查；确认写入时同样以样例
    文本作为校验语料，不会拿用户的文件内容去核对一批固定摘录。

边界:
    这不是"降级模式"，也不写入任何非样例事实；预览会带 `fixture=True` 标记，界面据此明确提示
    "当前为内置模拟数据"。生产环境由配置校验在启动时拒绝开启。
"""

import copy
import hashlib
from typing import Any

# 内置样例简历：已按 `import_service._normalize` 的规则折叠空白，便于逐字比对。
# 分段与下面的摘录一一对应，避免出现"跨段拼出来的摘录"这类无法命中的情况。
FIXTURE_TEXT = (
    "李雷 上海 高级后端工程师 "
    "五年后端开发经验，专注订单系统与性能优化 "
    "GitHub github.com/lilei "
    "熟悉 Python 与 PostgreSQL "
    "甲公司 后端工程师 负责订单系统重构 2020 年至 2022 年 "
    "订单系统重构 项目经理 技术栈 Spring Boot 主导订单链路拆分 2021 年至 2022 年 "
    "乙大学 计算机科学 学士 2016 年至 2020 年"
)

# 夹具文档哈希与样例文本绑定，但刻意不等于任何真实文件的哈希：避免被误读成"用户文件的指纹"。
FIXTURE_SOURCE_HASH = hashlib.sha256(b"jobark-profile-import-fixture-v1").hexdigest()

# 固定的结构化抽取结果；字段名与 `ImportCandidate` 契约一致，可直接经根信封校验。
# 不填邮箱与手机：夹具不生成任何联系方式，避免把编造的个人信息写进档案。
FIXTURE_EXTRACTION: dict[str, Any] = {
    "full_name": "李雷",
    "name_quote": "李雷",
    "headline": "高级后端工程师",
    "summary": "五年后端开发经验，专注订单系统与性能优化",
    "email": None,
    "phone": None,
    "city": "上海",
    "links": [{"label": "GitHub", "url": "github.com/lilei"}],
    "skills": [
        {"name": "Python", "source_quote": "熟悉 Python"},
        {"name": "PostgreSQL", "source_quote": "与 PostgreSQL"},
    ],
    "experiences": [
        {
            "company": "甲公司",
            "title": "后端工程师",
            "start_date": "2020-01-01",
            "end_date": "2022-01-01",
            "responsibilities": "负责订单系统重构",
            "source_quote": "甲公司 后端工程师 负责订单系统重构 2020 年至 2022 年",
        }
    ],
    "projects": [
        {
            "name": "订单系统重构",
            "role": "项目经理",
            "responsibilities": "主导订单链路拆分",
            "tech_stack": ["Spring Boot"],
            "start_date": "2021-01-01",
            "end_date": "2022-01-01",
            "source_quote": "订单系统重构 项目经理 技术栈 Spring Boot 主导订单链路拆分 2021 年至 2022 年",
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


def mock_extract_profile() -> dict[str, Any]:
    """返回固定的结构化抽取结果（mock 数据），用于临时替代大模型抽取。

    返回:
        dict[str, Any]: 与 `extract_profile_from_resume` 输出契约一致的固定 JSON；
            每次返回深拷贝，调用方改写不会污染模块常量。

    注意:
        这是**临时联调用的 mock**：既不调用大模型，也不读取上传文件的内容。它仍要经过
        `import_service` 的 Schema 与逐字原文校验，因此取值必须与 `FIXTURE_TEXT` 自洽——
        改这里的字段时，要同时保证对应摘录能在 `FIXTURE_TEXT` 里逐字找到。
    """
    return copy.deepcopy(FIXTURE_EXTRACTION)
