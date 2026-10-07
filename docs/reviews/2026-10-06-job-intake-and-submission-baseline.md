# 职位录入与投递设计的代码核对基线

核对日期：2026-10-06。HEAD：`5eafe662d02045d2bd6adad83c5f0ff36fb7c7a7`。开始时工作区无改动。本文是静态证据记录，不是任务状态、数据库部署证明或测试执行报告。

## 已实现的边界

| 范围 | 实际代码与测试证据 | 能证明什么／不能证明什么 |
| --- | --- | --- |
| 手工录入 | Job `models.py`、`schemas.py`、`service.py`；`JobListView.vue`；`test_job_api.py` | `channel_name`、公司 `description` 已有；手工来源仍为 MANUAL、链接可空。当前公司名、职位标题必填，只有 JD 不能保存。 |
| 内容导入 | Job `import_service.py`、`import_schemas.py`；`backend/app/automation/adapters/job_pages.py`；`test_job_import_api.py`、`test_job_page_adapters.py` | 四个平台详情 URL 识别，解析用户提供 HTML/TEXT，数据库候选、24 小时有效期、确认与固定回执。没有访问平台；JSON-LD 提取职位名称、公司名、地点、JD，未实现公司介绍抓取。 |
| 当前 JD | Job repository/service；`JobDetailView.vue`；`test_job_api.py`、`JobDetailView.test.ts` | 按 posting.current_snapshot_id；机会默认按 last_seen_at DESC、posting.id DESC；A→B→A 复用旧 A；历史查看不写指针。当前保存区域及时间语义已实现，不等于实时平台最新。 |
| 解析与匹配 | Job `analysis.py`、`parsing.py`；Matching `router.py`；`test_matching.py` | 独立本地／需外发确认的 AI 解析；匹配仍自行本地逐行解析，以 profile.skills 字面命中为主。简历模式过滤未表达技能，尚不能完整区分档案缺口与表达缺口；不消费用户选择的 JobParseResult；总分为空。 |
| 申请 | Application `models.py`、`service.py`；`test_application_api.py`；`ApplicationView.vue` | 尝试编号、重复申请确认、材料校验、状态事件与首次 APPLIED 材料锁。confirm_applied 确认过去已经投递，不授权未来发送。没有发送任务、材料清单授权、平台回执与核实接口。 |
| 调度 | `backend/app/main.py`、`backend/app/automation/tasks/__init__.py` | 生命周期没有启动采集调度；tasks 仅占位。自动搜索、小时执行、启动补跑、自动匹配尚未实现。 |
| 数据迁移 | migrations/versions 中 0004、0005、0006、0007、0011、0012、0013 | 0011 当前指针归属和申请锁等约束；0012 导入候选；0013 手工渠道及公司介绍。存在迁移文件不证明本机业务库已经应用；本轮没有查询或修改业务库。 |

后端模块在 `backend/app/modules/`，测试在 `backend/tests/`，页面与页面测试在 `frontend/src/features/job/`、`matching/`、`application/`。Company 规范化名称索引不唯一，不是跨渠道实体核实。JobOpportunity.company_id/title 目前不可空。快照是内容版本，不是每次观察记录；last_seen_at 是系统接受内容时间，captured_at 是该来源该内容首次采集时间。当前没有独立平台读取成功时间、获取历史或平台发布日期字段。

## 验证边界

本轮阅读根及 frontend/AGENTS.md、指定需求／设计、相关模型、迁移、服务、路由、页面和测试。测试文件中的案例是覆盖证据，本轮未运行业务测试、前端构建、浏览器验收、迁移或真实平台操作；历史测试结果不转记为本轮通过。

GitHub 连接器可读取 bigorange0923h/JobArk；全量 Issue 搜索及关闭 Issue 搜索未返回已有工作项，公开 Issues 页面也没有开放条目。未核实 Project 字段与全部历史分页，不把检索结果解释为 Project 已完成或没有依赖。未创建／更新 Issue，待实施前复查；[实施拆分](../implementation/job-intake-and-submission-issues.md)仅是可复制正文，不维护另一份执行状态。

## 官方平台资料与待验证假设

首个验证平台沿用已确认的 FIFTYONEJOB，不重新选平台。查阅官方[2024 年用户协议 PDF](https://fecdn.51jobcdn.com/fe/static/51job/%E7%94%A8%E6%88%B7%E5%8D%8F%E8%AE%AE/agreement_2024_05.pdf)（显示更新 2024-04-24、生效 2024-05-01）与[旧协议页面](https://login.51job.com/xyservice.php?display=h5&page=1)（显示 2021-09-23）。旧页有自动化访问限制；不能把旧页当作当前唯一适用版本，也不能从新 PDF 未检索到某个词推导自动化获准。官方求职与简历上传功能不证明第三方搜索、详情采集、上传或投递接口得到许可。

本轮未获得证明这些自动化能力获准且稳定可用的官方材料。适用协议、许可入口、真实详情完整性、读取频率、登录会话、可复核投递回执，均须单平台能力验证；不设计私有接口/token、验证码绕过或隐蔽采集。扩展其他平台须重新验证，四站本地内容解析不属于上述验证。
