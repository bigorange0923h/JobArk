# 简历导入：项目经历采集与候选可编辑设计

日期：2026-09-25
状态：已确认，待实施
关联需求：`docs/requirements/v1.md` 2.1 个人资料（Profile）

## 1. 背景与问题

当前简历导入只采集三类事实：技能、工作经历、教育经历（`ImportCandidate`）。实测导入一份包含项目经历的简历后，档案的 `projects` 为空，项目经历信息丢失；同时导入预览界面只能勾选条目，无法修正或补全 AI 提取的内容（例如补全职责、成果、技术栈）。

两个问题分别位于不同层面：

- 采集缺失：候选结构与提示词都没有项目经历，且模型配置为 `extra="forbid"`，模型即使返回项目也会导致结构校验失败（422）。
- 无法编辑：确认写入时后端重传原文件并校验「每个字段值必须逐字出现在该条 `source_quote` 中，且摘录必须逐字出现在原文」，因此自由编辑会直接触发 422。

导入写入后的事实可以由档案页的通用事实面板编辑，这部分能力已存在，本设计只需保证导入条目在其中可正常编辑，并给出引导。

## 2. 目标与非目标

目标：

1. 导入采集覆盖项目经历，字段与 `ProfileProject` 对齐。
2. 导入预览中可直接编辑候选（含基本信息），`source_quote` 只读。
3. 导入写入后仍可在档案页继续编辑（沿用既有事实面板）。
4. 不破坏「AI 不得编造」与「结论可追溯到证据」两条既有约束。

非目标：

- 不做扫描件 OCR。
- 不做导入历史回滚或版本化。
- 不引入后台任务状态库。

## 3. 关键决策：编辑与「逐字可定位」的共存

分两个阶段采用不同严格度，由 `_check_candidate(candidate, text, *, allow_edits)` 统一实现：

| 阶段 | allow_edits | 校验行为 |
| --- | --- | --- |
| 预览（`preview`） | `False` | 保持现状：摘录必须存在于原文；任一字段值不在摘录内、日期年份不在摘录内，一律 422。AI 编造的内容无法进入预览。 |
| 确认（`apply`） | `True` | 摘录仍必须存在于原文（拒绝编造摘录）；字段值或日期年份超出摘录时不再拒绝，而是把该条目标记为「用户修订」。 |

「用户修订」的落地方式采用**两级来源**：

- 未修订的条目：挂原有的「导入简历」证据（`RESUME_DOCUMENT`），内容为用户确认的原文摘录。
- 被修订的条目：改挂一条「本人陈述」证据（`MANUAL_DECLARATION`），标题形如 `导入修订：<文件名>`，内容为被修订条目的要点；该证据不带 `source_hash`（并非来自简历文件）。
- 两类条目的 `claim_status` 均为 `UNVERIFIED`，即仍然只是未验证候选。

这样「值来自简历」与「值由用户改写」在数据层可区分，架构约束不被破坏。基本信息（姓名、头衔、邮箱、手机、城市）写在档案根上，本身不带证据引用（手工建档同样如此），因此允许编辑，仅记录结构化日志。

已知取舍：确认阶段依赖客户端重传的候选，服务端无法区分「用户真的改过」与「客户端伪造」，但这是本地单用户工具，且候选仍以未验证状态、可读证据形式保存。

## 4. 实施内容

### 4.1 后端（`app/modules/profile/import_service.py`）

1. 新增 `SourcedProject`：`name`（必填）、`role`、`description`、`responsibilities`、`achievements`、`tech_stack`、`url`、`start_date`、`end_date`、`source_quote`（必填）。其中职责与成果是模型提取项目时的惯用字段（沿用工作经历的命名），写入时按段落合并进 `ProfileProject.description`——Profile 的项目事实只有这一列；合并只做拼接，不产生原文之外的内容。
2. `ImportCandidate` 增加 `projects`（上限 20）；`ImportConfirmRequest` 增加 `project_indices`；`ImportApplyRead` 增加 `projects_added`。
3. `_check_candidate` 改为返回「用户修订」的 `(分组, 下标)` 集合，并按上表区分严格度；新增项目分组的摘录与日期校验、项目起止日期顺序校验。
4. `preview` 的提取规则补充项目条款：仅在原文明确出现项目名称时输出；角色、说明、技术栈、链接只在摘录逐字覆盖时填写；日期缺失留空。
5. `apply` 按两级来源写入：先建「导入简历」证据（摘录来自未修订条目与姓名摘录），如有修订条目再建「本人陈述」证据并挂到对应事实；项目按名称规范化去重。
6. 结构化日志与统计补充 `project_count` / `projects_added`。

### 4.2 前端

1. `shared/api/profile.ts`：新增 `SourcedProject`，`ProfileImportCandidate` 增加 `projects`，`ProfileImportResult` 增加 `projects_added`，`confirmProfileImport` 透传 `project_indices`。
2. `components/ProfileImportPanel.vue`：候选条目由「只读 + 勾选」改为「可编辑表单 + 勾选」，字段控件沿用事实面板的形态（文本、多行、日期、标签、链接）；`source_quote` 只读展示；新增项目经历区块；基本信息可编辑；提交时发送编辑后的候选。

### 4.3 文档

`docs/requirements/v1.md` 2.1 补充项目经历采集与「预览可修正、修订条目以本人陈述为来源」。

## 5. 测试策略

后端（`tests/test_profile_import.py`）：

- 候选包含项目时，预览与确认写入项目，`projects_added` 正确。
- 模型编造项目字段时预览仍返回 422（严格模式未被放宽）。
- 确认阶段字段被改到摘录外时写入成功，被修订条目挂 `MANUAL_DECLARATION` 证据，未修订条目仍挂 `RESUME_DOCUMENT`。
- 摘录被改成原文中不存在的内容时，确认阶段仍返回 422。
- 重复项目按名称去重；越界的 `project_indices` 返回 422。

前端（`components/ProfileImportPanel.test.ts`）：

- 预览后编辑候选字段与新增项目，确认时提交的是编辑后的值。
- 项目区块按候选渲染。

## 6. 影响面

- 接口路径不变，仅请求/响应体字段增加，属向后兼容的契约扩展。
- 数据库无迁移：`profile_projects` 与 `profile_evidences` 结构足以承载新数据。
- 既有导入行为（三类事实、严格校验、去重、证据）保持不变。
