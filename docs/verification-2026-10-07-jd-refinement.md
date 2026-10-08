# JD 分析可靠性调整验证

## 范围与计划

用户明确要求依据只读评估形成修改计划并实施。计划见 [修改计划](implementation/jd-analysis-refinement-plan.md)，正式需求、架构、数据模型与 API 契约同步。GitHub 工作项只读查询返回空列表，不据此宣称不存在 Project，没有创建/更新远程 Issue。

## 交付

- literal-conditions-v3：跳过章节标题，安全拆分并列分句，保留逐字出处/位置/组关系。OR 整体待确认；未识别准入保持 UNKNOWN，不因遗漏移除维度。经验对象只记录明确原文，泛化“相关经验”不推算为技术年限。
- six-dimensions-v2：目标方向与补充关键词分开，标题/正文/关键词线索分别解释。薪资期望和独立底线分开，明确同口径比较，跨底线未知；超过期望上限不扣分。仍是保守线索和产品参考锚点，不能称为已校准语义匹配。
- 教育新增可空 degree_level/study_mode，贯通日常表单、API、修订与本人确认的导入。旧 degree 保留，不回填真实学历；模型预览的结构化学历不直接采用，用户补录按本人陈述归因。
- 报告保存事实判断摘录及来源支持程度，提供项目技术栈/归属、方向、薪资口径、教育确认的行动入口。不把来源附件当成能力独立核验。
- 0017 增量迁移及有数据拒绝降级。隔离迁移验证暴露原 0015 downgrade 的 JSON 冒号被 SQLAlchemy 当绑定参数的问题，改为 jsonb_build_object，未改旧 upgrade 行为。

## 自动验证

后端八文件集合（test_jd_refinement、test_jd_analysis、test_jd_analysis_migration、test_migrations、test_profile_api、test_profile_import、test_matching、test_exclusions）统一运行 **116 passed**。包括真实 PostgreSQL 的随机 schema API、升降级、拒绝丢失及 ORM 对齐；业务 schema 不参与这些测试。末次经验对象收紧后，受影响子集 **33 passed**；重复检查不累加。

前端 StrategyView、ProfileManualFacts、ProfileImportPanel、MatchingView 最终 **48 passed**；接口使用替身。新增独立底线与关键词保存、教育字段保存/来源归因、报告补充入口和来源支持显示回归。ESLint、vue-tsc/Vite build 通过，后端 Ruff check、受影响文件 format check 和 Pyright（0 errors/warnings）通过。jsdom 报 getComputedStyle 伪元素未实现警告，不能据组件测试声称视觉验收。

## 本机业务库升级

确认目标为 127.0.0.1:5432/jobark/public，起点 0012。复核 0013–0017：新增渠道/公司介绍、放宽 JD-only、新增工作条件/策略/解析引用、独立公司报告表、学历与策略增量。未删除、批量更新或推断用户事实。

通过 Alembic 绑定单个事务升级至 **0017**，设置锁等待5秒和语句30秒；事务中对 **27 张原有业务表**逐表比较原有列的规范化 SHA256 与记录数，全部一致后才提交。提交后另连读取迁移版本确认0017；不输出正文、凭据或密钥摘要。个人资料仍为24技能、4工作、6项目、1教育、1来源；资料修订和正式简历版本仍为0，真实JD/解析/匹配未代建。

当前代码通过 TestClient/ASGI 连接真实业务库，只读 GET /profile、/profile/preference、/jobs、/matches，均200/success=true；新教育和策略字段出现在响应中。这验证当前代码读取真实库，不能代替已运行开发服务的重载或浏览器端到端交互。

## 未验收边界

没有外发真实JD/履历，没有调用真实模型或搜索。没有真实JD数据，无法评估模型回答质量和业务适配准确率。浏览器桌面/窄屏视觉验收未完成；组件测试和生产构建不能代替它。没有部署、push、自动投递或代填求职意愿。用户仍需确认实际方向、税口径、学历形式，以及项目技术栈和工作归属。

## 同方向收尾

用户再次确认方向后，补齐仅设置薪资底线（包括0）且没有税口径的报告提示，以及方向、关键词、底线、税口径字段的就地校验反馈。先增加复现测试，两项在修改前失败；修改后 test_jd_refinement **9 passed**、StrategyView **13 passed**，Ruff/受影响后端格式检查、前端 ESLint 与 vue-tsc/Vite build、git diff --check 通过。此处是受影响回归，不与上述集合累计；未再次修改业务库，也未替用户填写实际意愿或履历。

## 2026-10-08 提交前复核

重新运行上述后端八文件集合，结果 **117 passed**；数据库夹具使用同库随机 schema、隔离连接及事务，不升级或改写业务 schema。前端上述四文件集合 **49 passed**，ESLint、vue-tsc/Vite build 通过；jsdom 仍提示伪元素 getComputedStyle 未实现。后端 Ruff check、14 个受影响文件 format check、Pyright（0 errors/warnings）及 git diff --check 通过。此处为当前提交前复核，不与历史结果累计；没有重新执行业务库升级、浏览器验收、真实模型或搜索调用。
