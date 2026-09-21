# JobArk V1 架构设计

## 1. 状态与范围

**已验证事实：**仓库当前是一个 Python/FastAPI 启动项目，根目录含 `main.py` 与 `pyproject.toml`；尚未有前端、数据库迁移或领域模块实现。

**本设计的目标：**将项目演进为单仓库的个人求职工作台。V1 覆盖 Profile、Resume、手动录入职位与 JD 分析、可解释匹配、Application 流程和 Dashboard。

**不属于 V1：**自动提交职位、多 Agent、LangGraph、向量数据库/RAG、微服务、消息队列和多租户。浏览器自动化即使以后加入，也只能通过接口调用，不能成为业务事实的唯一来源。

## 2. 关键架构决定

| 决定 | 原因 | 边界 |
| --- | --- | --- |
| 单仓库，前后端分目录 | 便于联合开发、部署和 API 契约维护 | 不等同于共享业务代码 |
| 按领域组织后端模块 | 聚合模型、服务、仓储和 API，避免全局 `services/` 堆积 | 跨领域事务须由显式应用服务协调 |
| PostgreSQL 保存业务事实 | 可复现、可审计的职位、简历和投递数据不能仅保存在模型上下文 | 开发期可用替代数据库，但不得把其行为当作生产等价物 |
| Profile 与 Resume 分离 | Profile 是真实证据库；简历是可版本化的表达视图 | AI 只能引用 Profile 证据，不能新增事实 |
| Opportunity、Posting、Snapshot 分离 | URL、职位机会和某次 JD 内容并非同一概念 | 去重结论需要置信度和人工可纠正能力 |
| Application 加 Event | 生命周期可追溯，避免在职位上累积状态布尔值 | `current_status` 是事件投影，不能绕过事件直接改写 |
| LLM 是受控能力层 | 输出必须满足 Pydantic 契约并包含证据、缺口和不确定项 | LLM 无权写业务事实或触发投递 |

## 3. 运行时边界

```text
Vue 3 Web
    │ REST / SSE
    ▼
FastAPI application
    ├── profile / resume / job / matching / application / dashboard
    ├── AI services (JD parser, matcher, resume optimizer)
    └── automation port (Phase 5+)
             │
             ├── PostgreSQL: business facts
             └── browser adapters: external side effects
```

浏览器适配器、LLM Provider 和调度器均是可替换基础设施。领域服务只能依赖它们定义的端口，不得依赖具体平台页面或模型 SDK。

数据库使用 PostgreSQL 16。开发与部署镜像位于 `deploy/postgres/`，根目录 `compose.yaml` 是唯一的 Compose 服务入口，并与根目录 `.env` 配对；基础镜像固定到已验证的官方摘要，V1 仅初始化 `pgcrypto`、`pg_trgm` 和 `unaccent`，业务表结构一律通过 Alembic 管理。该选择为职位/公司文本检索、版本化数据与统计查询提供稳定基础，且不提前引入 V1 范围外的向量检索能力。

## 4. 前端技术架构与能力

前端技术栈正式确定为：**Vue 3 + TypeScript + Vite + Ant Design Vue + ECharts**。

| 层级 | 技术/位置 | 职责 |
| --- | --- | --- |
| 应用层 | Vue 3、`frontend/src/app/` | 应用启动、路由、布局、全局错误处理与页面级权限预留 |
| 页面功能层 | `frontend/src/features/` | Dashboard、Jobs、Profile、Resume、Applications 等领域页面和领域组件 |
| UI 层 | Ant Design Vue | 表格、表单、抽屉、步骤条、通知、确认弹窗与一致的交互规范 |
| 可视化层 | ECharts | 求职漏斗、来源分布、投递趋势、简历版本转化等数据图表 |
| 共享层 | `frontend/src/shared/` | API Client、类型、通用组件、格式化工具与可复用组合式函数 |
| 构建层 | Vite | 本地开发服务器、TypeScript 构建、环境变量注入和生产打包 |

前端负责呈现和编辑用户已确认或待确认的数据，不拥有领域规则：例如状态流转、匹配评分、证据校验和自动化权限都在后端执行。所有会引起外部副作用的操作（如后续投递）必须以显式确认界面收口。

V1 前端能力包括：

- Dashboard：关键计数、漏斗、来源分布、趋势和待处理项；ECharts 图表须提供表格/数值替代，避免图表成为唯一信息源。
- Jobs：职位列表、JD 快照、Profile/Resume 双匹配报告、证据与缺口展示、收藏/忽略/准备投递。
- Profile：个人事实与证据的结构化维护；不允许将 AI 推断直接保存为事实。
- Resume：多份 Resume、版本记录、结构化编辑、A4 预览、导出入口和 AI 候选修改对比。
- Applications：当前状态、事件时间线、关联的职位和 ResumeVersion，以及手动状态更新。

## 5. 领域数据与约束

```text
PersonalProfile ──< ProfileEvidence
       │
       └──< Resume ──< ResumeVersion

Company ──< JobOpportunity ──< JobPosting ──< JobSnapshot
                                  │
JobOpportunity ──< MatchResult >── ResumeVersion / PersonalProfile
       │
       └──< Application ──< ApplicationEvent
```

- `JobSnapshot` 固化当时的原始与结构化 JD；匹配结果必须指向其输入快照和 Profile/Resume 版本。
- `MatchResult` 分开保存 Profile Match 和 Resume Match，保存维度评分、证据引用、缺口与不确定项，而非只有百分比。
- `Application` 表示一次求职行为，绑定使用的 `ResumeVersion`；`ApplicationEvent` 是唯一的状态历史。
- 简历定制、问候语和表单回答均为候选草稿，需用户确认后才能进入提交类操作。

## 6. 目录约定

```text
JobArk/
├── backend/
│   ├── app/
│   │   ├── core/                 # 配置、数据库、错误与日志
│   │   ├── modules/              # 业务优先分包
│   │   │   ├── profile/
│   │   │   ├── resume/
│   │   │   ├── job/
│   │   │   ├── matching/
│   │   │   ├── application/
│   │   │   └── dashboard/
│   │   ├── ai/                   # 受控 LLM 能力和输出契约
│   │   └── automation/           # Phase 5+ 的端口和适配器
│   ├── migrations/
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/                  # Vue 路由、布局、Vite 启动配置
│       ├── features/             # Dashboard/Jobs/Profile/Resume/Applications
│       └── shared/               # AntDV 封装、ECharts 图表、API 与通用工具
├── docs/                         # 可提交的工程文档
├── deploy/                       # Compose、Nginx 和部署配置
└── scripts/                      # 可重复执行的开发/运维辅助脚本
```

每个后端领域模块后续按需要增加 `router.py`、`service.py`、`repository.py`、`models.py`、`schemas.py` 与 `enums.py`；不预先创建空实现文件。根目录现有 `main.py` 是启动示例，迁移到 `backend/app/main.py` 应与首次后端初始化提交一并完成，避免双入口。

## 7. V1 实施顺序

1. 初始化后端工程：配置、数据库、Alembic、健康检查、测试约定。
2. 实现 Profile、证据与 Resume/ResumeVersion；完成结构化编辑与 HTML/CSS 预览。
3. 实现 Job、Posting、Snapshot 和手动 JD 录入；再接入受控 JD 解析与匹配。
4. 实现 Application/Event、漏斗与 Dashboard 投影。
5. 接入只读职位发现；所有外部写入仍默认需要人工确认。

## 8. 实施前必须验证的假设

- 目标招聘平台是否允许抓取、自动化填写或状态同步；不得假设所有网站能力相同。
- 去重是否能依赖公司、标题、地点和 JD 相似度；必须提供人工合并/拆分入口。
- PDF 导出在目标部署环境中的 Chromium 字体与分页是否稳定。
- 匹配评分的权重与“硬性淘汰”规则需用真实职位样本校准，不能先把模型分数当作事实。
- 当前 `pyproject.toml` 的 Python 3.14 要求与设计稿的“3.12+”不同；后端初始化时需明确支持版本并在 CI 固化。
