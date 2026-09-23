# JobArk V1 架构设计

## 1. 状态与范围

后端是位于 `backend/` 的独立 Python 工程（`backend/pyproject.toml`、`backend/uv.lock`、唯一入口 `backend/app/main.py`，`requires-python >= 3.14`）。`app/core/` 负责配置、结构化日志、请求标识、统一响应与异常处理，数据访问使用异步 SQLAlchemy 与 Alembic。前端是位于 `frontend/` 的独立 npm 工程（Vite + Vue 3 + TypeScript + Vue Router + Ant Design Vue 按需导入 + API Client）。业务按 Profile、Resume、Job、Matching、Application 和 Dashboard 分域，形成个人求职的人工记录闭环。

分析能力遵循[ADR 0003](adr/0003-求职闭环与分析边界.md)：JD 原文与独立解析产物分离；默认本地逐行提取与字面证据匹配，不输出未经校准的分数。可选 AI 网关用于带逐字引用的 JD 解析、简历已有条目的筛选和重排，必须确认外部发送；它不是开箱即用的商业模型集成，协议与配置见 [AI 网关](ai-gateway.md)。

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
    │ REST
    ▼
FastAPI application
    ├── profile / resume / job / matching / application / dashboard
    ├── local evidence matching
    └── optional JSON AI gateway (JD parser, resume selector)
             │
             ├── PostgreSQL: business facts
             └── configured AI endpoint: explicit consent
```

浏览器适配器、LLM Provider 和调度器均是可替换基础设施。领域服务只能依赖它们定义的端口，不得依赖具体平台页面或模型 SDK。

数据库使用 PostgreSQL 16。开发与部署镜像位于 `deploy/postgres/`，根目录 `compose.yaml` 是唯一的 Compose 服务入口，并与根目录 `.env` 配对；基础镜像固定到已验证的官方摘要，V1 仅初始化 `pgcrypto`、`pg_trgm` 和 `unaccent`，业务表结构一律通过 Alembic 管理。该选择为职位/公司文本检索、版本化数据与统计查询提供稳定基础，且不提前引入 V1 范围外的向量检索能力。

### 3.1 请求与响应契约

后端 HTTP 层遵循 ADR 0001 固化的契约，细节与错误码表以该 ADR 为准：

- 成功响应为 `{success: true, data, meta}`，失败响应为 `{success: false, error, meta}`；分页等附加信息放入 `meta`。
- 路由显式返回 `ApiResponse[T]`，失败由 `app/core/exception_handlers.py` 集中构造，业务代码只抛 `AppError` 子类。
- `request_id` 由请求上下文中间件建立并贯穿响应头、响应体与服务端日志；入站 `X-Request-ID` 经白名单校验后沿用。
- 日志为单行 JSON，字段集合固定；`uvicorn.access` 被关闭，访问日志统一由中间件产出，以保证每条都带 `request_id`。
- 应用配置从环境变量与 `backend/.env` 读取，统一使用 `JOBARK_` 前缀；仓库根目录的 `.env` 仅供 `compose.yaml` 使用。两者命名空间分离，避免把数据库凭据误读为应用配置。
- 跨域默认关闭：开发期前端通过 Vite 代理使用相对路径访问后端（同源），生产同源部署，都不需要 CORS。只有前后端确实分离到不同源时，才通过 `JOBARK_CORS_ALLOWED_ORIGINS`（逗号分隔白名单）显式启用，并暴露 `X-Request-ID` 供前端读取。已知限制：未捕获异常产生的 500 由 Starlette 最外层中间件生成，不经过 CORS 中间件，跨域场景下浏览器会把 500 报成 CORS 错误，排查时需直接访问后端地址。

### 3.2 数据访问与迁移

数据访问细节与取舍见 ADR 0002，要点如下：

- 数据库 I/O 全异步（`AsyncSession` + asyncpg），Alembic 同样使用异步 `env.py`；纯计算（评分、校验、字段转换）保持普通 `def`。
- 事务边界由应用服务显式控制，会话依赖不做隐式提交；服务顺序固定为**取数据 → 结束事务 → 等待外部 → 按需开启新事务写回**，禁止在持有事务时等待 LLM、浏览器或第三方 HTTP。
- 每个请求与后台任务各自获取会话，不跨请求复用。
- `Base` 与约束命名约定定义在 `app/core/database.py`；`migrations/env.py` 显式导入各领域 `models`，新增领域必须在此追加导入，否则 autogenerate 会静默漏表。
- `alembic.ini` 不保存连接串且必须保持 ASCII-only（`configparser` 按本地编码读取）；版本号使用可读递增编号。
- 质量护栏：Pyright `strict`、pytest 警告即失败、Ruff（`check` + `format`）。GitHub Actions 配置位于 `.github/workflows/checks.yml`，数据库测试只使用独立 `jobark_test`；提交前仍需本地验证，不能把配置文件等同于远端运行成功。

## 4. 前端技术架构与能力

前端技术栈为：**Vue 3 + TypeScript + Vite + Ant Design Vue + ECharts**。UI 组件与图表按需导入，业务页面使用路由懒加载，避免把所有领域放入入口包。

| 层级 | 技术/位置 | 职责 |
| --- | --- | --- |
| 应用层 | Vue 3、`frontend/src/app/` | 应用启动、路由、布局与全局错误处理；不预留多用户权限体系 |
| 页面功能层 | `frontend/src/features/` | Dashboard、Jobs、Profile、Resume、Applications 等领域页面和领域组件 |
| UI 层 | Ant Design Vue | 表格、表单、抽屉、步骤条、通知、确认弹窗与一致的交互规范 |
| 可视化层 | ECharts | 求职漏斗、来源分布、投递趋势、简历版本转化等数据图表 |
| 共享层 | `frontend/src/shared/` | API Client、类型、通用组件、格式化工具与可复用组合式函数 |
| 构建层 | Vite | 本地开发服务器、TypeScript 构建、环境变量注入和生产打包 |

前端质量检查包括 ESLint、Vitest、TypeScript 严格检查与 Vite 生产构建。漏斗图使用 ECharts，核心指标同时保留表格或数值呈现。

API Client 的分层与边界：

- `shared/api/types.ts` 手工镜像后端统一契约，领域类型与端点封装按模块维护。
- `shared/api/client.ts` 是**唯一的解包点**：成功返回 `data`，失败抛出携带 `code`/`message`/`status`/`requestId`/`details` 的 `ApiError`。
- 具体端点封装放在 `shared/api/` 或阶段 1 起各领域的 `features/<domain>/api.ts`。
- 错误码原样透传供调用方分支，展示默认使用后端 `message`，前端**不复制一份文案表**（必然漂移）；`requestId` 附着在错误对象上，便于展示"错误编号"并定位服务端日志。
- 不自动重试：写操作重试可能造成重复提交。

前端负责呈现和编辑用户已确认或待确认的数据，不拥有领域规则：例如状态流转、匹配评分、证据校验和自动化权限都在后端执行。所有会引起外部副作用的操作（如后续投递）必须以显式确认界面收口。

V1 前端能力包括：

- Dashboard：工作台默认首页和侧栏首项；展示关键计数、漏斗、来源分布、趋势和待处理项；ECharts 图表须提供表格/数值替代，避免图表成为唯一信息源。
- Jobs：职位列表、JD 快照、Profile/Resume 双匹配报告、证据与缺口展示、收藏/忽略/准备投递。
- Profile：个人事实与证据的结构化维护；简历 PDF 的文字层用 pypdf 本地提取，HTML 用标准库解析并忽略脚本/样式，不抓取外部资源。上传内容限制大小与页数，仅在用户确认后将提取文本发往现有 AI 网关；模型输出以原文摘录校验并由用户逐项确认，未确认候选不落库，确认后以一份未验证来源证据关联新增事实，不覆盖已有档案。不支持扫描件 OCR；网关未配置时安全失败并允许手工录入。
- Resume：多份 Resume、版本记录、结构化编辑、A4 预览、导出入口和 AI 候选修改对比。
- Applications：当前状态、事件时间线、关联的职位和 ResumeVersion，以及手动状态更新。

## 5. 领域数据与约束

表模型、不可变快照边界、关键约束与实施顺序见[数据模型设计](data-model.md)。JobArk 按单人本地工具建模，不预留多租户、用户或组织边界。

```text
PersonalProfile ──< ProfileEvidence
       │
       ├──< ProfileRevision ──< ResumeVersion
       └──< Resume ──< ResumeVersion / ResumeDraft

Company ──< JobOpportunity ──< JobPosting ──< JobSnapshot
                                  │
JobOpportunity ──< MatchResult >── ResumeVersion / PersonalProfile
       │
       └──< Application ──< ApplicationEvent
```

- `JobSnapshot` 固化原始 JD；后续解析保存为独立 `JobParseResult`，失败不覆盖快照。
- `MatchResult` 分开保存 Profile Match 和 Resume Match，绑定快照、资料修订和可选简历版本；`report_json` 固化本地解析器版本、条件、证据引用、缺口和不确定项，总分留空。独立 AI 解析结果不会悄悄替换匹配输入。
- `Application` 表示一次求职行为，绑定使用的 `ResumeVersion`；`ApplicationEvent` 是唯一的状态历史。
- 简历定制、问候语和表单回答均为候选草稿，需用户确认后才能进入提交类操作。

## 6. 目录约定

```text
JobArk/
├── backend/                      # 后端 Python 工程根：pyproject.toml、uv.lock、app/
│   ├── app/
│   │   ├── main.py               # 唯一 FastAPI 入口：create_app 与模块级 app
│   │   ├── core/                 # 配置、日志、错误与响应契约（契约见 ADR 0001）
│   │   │   ├── config.py         # Settings：JOBARK_ 前缀，backend/.env 可选
│   │   │   ├── database.py       # Base、约束命名约定、异步引擎与会话依赖
│   │   │   ├── context.py        # request_id 的 ContextVar 载体
│   │   │   ├── logging.py        # 单行 JSON 日志格式化与 uvicorn 日志收口
│   │   │   ├── errors.py         # AppError 体系与稳定错误码
│   │   │   ├── responses.py      # ApiResponse / ApiErrorResponse 契约与公共响应基类
│   │   │   ├── versioning.py     # 可编辑实体的乐观锁条件更新
│   │   │   ├── middleware.py     # 请求上下文中间件与结构化访问日志
│   │   │   └── exception_handlers.py  # 四类异常的统一收口
│   │   ├── modules/              # 业务优先分包
│   │   │   ├── profile/          # router/service/repository/models/schemas/enums
│   │   │   ├── resume/           # 同上；含不可变简历版本与 AI 候选稿状态机
│   │   │   ├── job/
│   │   │   ├── matching/
│   │   │   ├── application/
│   │   │   └── dashboard/
│   │   ├── ai/                   # 受控 LLM 能力和输出契约
│   │   └── automation/           # Phase 5+ 的端口和适配器
│   ├── .env.example              # 后端应用配置示例（JOBARK_ 前缀）
│   ├── alembic.ini               # 迁移配置：不含凭据，且必须保持 ASCII-only
│   ├── migrations/
│   │   ├── env.py                # 异步迁移环境；领域模型在此显式导入
│   │   ├── script.py.mako        # 迁移脚本模板
│   │   └── versions/             # 迁移脚本，可读递增编号（0001、0002……）
│   └── tests/                    # 契约测试 + 数据库集成测试（缺测试库时自动跳过）
├── frontend/                     # 独立 npm 工程根：package.json、vite.config.ts、tsconfig.json
│   └── src/
│       ├── main.ts               # 应用入口
│       ├── App.vue               # 根组件：最外层布局与路由出口
│       ├── app/                  # 路由与页面（views/）；Vite 启动配置在工程根
│       ├── features/             # 领域页面容器，阶段 1 起按 Dashboard/Jobs/… 填充
│       └── shared/
│           └── api/              # API Client：契约类型、解包、端点封装与单元测试
├── compose.yaml                  # 唯一的 Compose 服务入口，与根目录 .env 配对
├── docs/                         # 可提交的工程文档
├── deploy/                       # Compose、Nginx 和部署配置
└── scripts/                      # 可重复执行的开发/运维辅助脚本
```

每个后端领域模块后续按需要增加 `router.py`、`service.py`、`repository.py`、`models.py`、`schemas.py` 与 `enums.py`；不预先创建空实现文件。后端入口已完成迁移：`backend/app/main.py` 是仓库内唯一的 ASGI 入口，根目录不再保留 Python 工程文件，双入口已被消除；包边界由各目录的 `__init__.py` 固定。

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
- 后端解释器版本为 `>=3.14`，依赖与 `backend/uv.lock` 保持一致；远端 CI、目标部署环境字体与真实 AI 网关必须分别验证，本地通过不能替代这些环境的验收。
