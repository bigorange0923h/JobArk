# JobArk V1 架构设计

## 1. 状态与范围

后端是位于 `backend/` 的独立 Python 工程（`backend/pyproject.toml`、`backend/uv.lock`、唯一入口 `backend/app/main.py`，`requires-python >= 3.14`）。`app/core/` 负责配置、结构化日志、请求标识、统一响应与异常处理，数据访问使用异步 SQLAlchemy 与 Alembic。前端是位于 `frontend/` 的独立 npm 工程（Vite + Vue 3 + TypeScript + Vue Router + Ant Design Vue 按需导入 + API Client）。业务按 Profile、Resume、Job、Matching、Application 和 Dashboard 分域，形成个人求职的人工记录闭环。

分析能力遵循[ADR 0003](adr/0003-求职闭环与分析边界.md)：JD 原文与独立解析产物分离；默认本地逐行提取与字面证据匹配，不输出未经校准的分数。可选大模型服务（用户可见术语；文件与模块名保留历史 `gateway` 命名）用于带逐字引用的 JD 解析、简历已有条目的筛选和重排以及简历导入候选，必须确认外部发送；所有 AI 调用一律使用工作台内唯一默认启用模型，未配置时安全失败并提示前往配置页。用户可配置多个 OpenAI 兼容服务商与模型并选择唯一默认模型；凭据以数据库密文保存，根密钥不入库，边界见 [ADR 0004](adr/0004-ai-model-configuration.md) 与[大模型服务协议](ai-gateway.md)。

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
| AI 模型配置保存于数据库 | 单人用户可维护多个 OpenAI 兼容模型并在页面选择默认模型 | API Key 仅存加密密文，根密钥不入库；不支持厂商 SDK 或用途级路由 |

## 3. 运行时边界

```text
Vue 3 Web
    │ REST
    ▼
FastAPI application
    ├── profile / resume / job / matching / application / dashboard
    ├── local evidence matching
    └── optional OpenAI-compatible AI gateway (unique default model; JD parser, resume selector)
             │
             ├── PostgreSQL: business facts and encrypted model configuration
             └── configured AI endpoint: explicit consent
```

浏览器适配器、LLM Provider 和调度器均是可替换基础设施。领域服务只能依赖它们定义的端口，不得依赖具体平台页面或模型 SDK。

数据库使用 PostgreSQL 16。开发与部署镜像位于 `deploy/postgres/`，根目录 `compose.yaml` 是唯一的 Compose 服务入口，并与根目录 `.env` 配对；基础镜像固定到已验证的官方摘要，V1 仅初始化 `pgcrypto`、`pg_trgm` 和 `unaccent`，业务表结构一律通过 Alembic 管理。该选择为职位/公司文本检索、版本化数据与统计查询提供稳定基础，且不提前引入 V1 范围外的向量检索能力。

### 3.1 请求与响应契约

后端 HTTP 层遵循 ADR 0001 固化的契约，细节与错误码表以该 ADR 为准：

- 成功响应为 `{success: true, data, meta}`，失败响应为 `{success: false, error, meta}`；分页等附加信息放入 `meta`。
- Profile 导入预览保留一次性 JSON 接口；界面使用同一处理流程的 `text/event-stream` 接口接收固定阶段码，最终 `result`/`error` 事件仍携带统一响应包与 `request_id`。流开始后的错误以终止事件表达，断流按失败处理；不引入后台任务状态库。
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
- Profile：个人事实与证据的结构化维护；简历 PDF 的文字层用 pypdf 本地提取，HTML 用标准库解析并忽略脚本/样式，不抓取外部资源。上传内容限制大小与页数，仅在用户确认后将提取文本发往已配置的大模型服务；模型输出以原文摘录校验并由用户逐项确认。导入入口是页面主按钮，选择后直接弹出文件选择弹窗并在其中说明外发范围与“不自动写入档案”，用户看到外发范围与重试策略的醒目提示后点击「继续」即构成同意并调用预览接口（不再要求额外勾选）；上传阶段按浏览器上报的真实字节显示进度（总量不可得时不显示百分比），模型阶段只显示真实阶段码。预览根信封保持严格，基本信息是整体可信锚点；技能、工作经历、项目经历与教育经历分别做 Schema 与证据校验，坏条目通过 `rejected_items` 报告且不进入候选，未映射字段通过 `warnings` 可见呈现，结果以 `completeness=PARTIAL` 明示不能代表抽全。项目的名称和摘录无效时整条拒绝；其余项目字段缺少逐字证据时清空为候选缺口并通过 `warnings` 告知，保留可验证项目骨架；模型沿用工作经历命名的项目字段（如 `title`）与字符串技术栈在校验前归一化（`FIELD_ALIAS_MAPPED`），归一化后仍须逐字落在摘录中。预览仅在明确的连接失败、429 或 5xx 时自动重试一次；超时、协议、结构和证据失败不重试。候选在确认前可逐字段修正、增删条目，来源摘录保持只读。条目来源是显式契约（`origin`）：`RESUME` 必须携带真实摘录、预览与确认都逐字校验，`MANUAL` 不接受摘录（携带即 422）——靠假摘录把用户新增内容伪装成简历原文的路被堵死，而用户也不需要为新增条目编造原文。用户改到摘录之外的 `RESUME` 条目在确认时降级为 `MANUAL` 并改挂未验证的本人陈述证据，不再沿用旧摘录作为新内容的证明。确认后编辑事实时同样重新归因：内容字段一变且原来源是简历文档证据，就改挂固定的「本人编辑：内容修订」证据（历史证据保留，不要求用户补交任何证明）。来源证据不是使用门槛：技能等事实可以不挂证据即保存，并照常参与匹配与简历生成，只有标记为「已验证」时才要求有效证据（应用层与数据库层同时约束）。匹配报告把命中写成"档案事实的字面匹配"并区分是否另挂来源记录（`FACT_FOUND` / `EVIDENCE_ATTACHED` / `UNKNOWN`），不暗示能力、年限或整项条件已核实，也不输出招聘概率。档案尚未创建时，手动创建与从简历导入两条路径在当前页动态展开、互斥展示（不跳转到独立页面；选择导入即隐藏创建表单，返回手动创建不落库且保留内存候选），确认导入后刷新聚合并展示正式档案；候选中缺少的可选字段显示为空、确认时写 `null`/空数组，姓名等必填领域约束不放宽。基本信息表单在创建与编辑两处都是"离开输入框即自动保存"（不提供保存按钮）：没有改动不发请求，姓名留空或公开链接只填一半时先不保存并就地提示，保存状态一直可见，连续编辑使用保存响应返回的最新版本号以避免页面尚未重新加载造成的假冲突。创建档案页与候选基本信息区由同一个 `ProfileBasicsSection` 组件渲染：字段定义、顺序、标签、帮助文本、控件形态与字段网格（桌面端每行最多两个普通字段、长文本独占一行、窄屏单列）只有一份实现，两页不再各写一份相似模板；两页的字段集合来自同一份定义（后端 `ImportCandidate` 与创建档案表单一一样包含姓名、头衔、个人简介、邮箱、手机、城市与公开链接），公开链接由共享的 `ProfileLinksField` 渲染。个人简介与公开链接按字段级隔离校验：取值无法逐字定位（链接地址按去掉协议前缀比较，名称同样要来自原文）时只清空这两个字段并通过 `warnings` 告知，不会因此丢弃同一份简历的其它候选；确认阶段用户补充到摘录之外的内容记为本人陈述；确认导入只在新建档案时写入这两个字段，已有档案不覆盖（界面把这两个字段显示为只读并说明原因）。确认后的条目可在档案页各事实面板继续编辑；已有档案只补充事实，不覆盖根信息。不支持扫描件 OCR；大模型服务未配置时安全失败并允许手工录入。为在未配置模型时联调，另提供默认关闭的内置夹具（`JOBARK_PROFILE_IMPORT_FIXTURE`）：固定抽取结果与内置样例文本互相自洽，仍走同一套 Schema 与逐字证据校验，预览带 `fixture` 标记并在界面明确提示，仅 local/test 可用。档案页不设独立的证据管理面板：一块写着"证据／可核验程度／已验证"的表格会被读成"系统已核实这些能力"，而它只是来源记录；证据由导入与本人填写流程自动创建，只在单条事实的上下文（编辑弹窗的「来源与状态」、事实表格的来源列）中可查看。

所在城市由共享表单使用省市两级选择器，选项数据通过锁定版本的 `cn-division` 随前端打包，运行时不请求第三方地址服务；接口仍保存城市字符串。旧值按名称回显，无法映射的国内旧称及海外城市走手动填写，避免区划数据更新导致原有档案不可编辑。该选项数据只辅助输入，不承担行政区划合规校验或地址真实性判断。

个人资料的核心编辑区由 `ProfileBasicsSection`、`ProfileLinksField` 与 `ProfileFactSections` 组合：基本信息、公开链接及技能、工作经历、项目经历、教育经历在手动与导入模式使用同一份字段定义和控件。`ProfileManualFacts` 负责合法条目失焦后的自动保存，建档前只暂存草稿；`ProfileImportPanel` 负责候选填充、只读的条目级原文摘录和本地草稿，用户点击专门保存按钮并通过二次弹窗后才调用确认接口。后端尚无逐字段出处，界面不得把条目级摘录说成每个字段的精确出处。证据、语言和修订历史保留在次级展开区，不从数据库删除。旧事实面板的手动保存流程已由核心表单取代；导入仍不覆盖已有档案的根信息。

导入入口固定在「档案与联系方式」标题右侧，空档案也直接显示手动表单。文件上传弹窗只负责外发告知与抽取；抽取成功后关闭上传弹窗，打开包含已填充共享表单的核对弹窗。核对弹窗内确认即调用导入确认接口，成功后关闭弹窗并重新读取档案聚合；取消时保留内存草稿且不写库。核对弹窗本身已经是上传后的第二层提醒，不再额外叠加确认弹窗。

技能在 `ProfileFactSections` 中单独使用双列紧凑卡片（窄屏单列），只显示点击可编辑的名称、来源和右侧删除按钮；回车或失焦结束编辑并沿用所在模式的保存策略。导入候选的来源显示条目级原文摘录；已保存技能根据 `source_evidence_id` 查找证据标题，无关联时标为「本人填写」。证据标题不是逐字段原文引用，不能据此推断技能已被独立验证。

个人资料表单的即时校验失败由 `shared/feedback/formNotice.ts` 发出语义化通知，沿用 Alert 的浅色背景与边框；首次校验失败时自动滚动和聚焦首个错误字段，通知不提供二次定位操作。字段旁错误与表单内可恢复的简短摘要继续保留，避免通知消失后丢失修正上下文。上传隐私说明、部分抽取结果和夹具标识仍是持续可见的状态提示，不作机械替换。

学历/学位用同一套做法：`DegreeField` 提供常见学历选项（高中／中专／大专／本科／本科（非全日制）／硕士／博士）加「其他（手动填写）」，档案页教育经历与导入候选教育条目共用它，选项定义只有一份（`frontend/src/features/profile/degrees.ts`）。学习形式是本人陈述，只能由用户选择，不由学校或年份推断。后端 `degree` 是自由字符串而不是枚举，历史数据与模型抽取里存在「学士」「研究生」这类列表外写法：选择器必须原样回显并保存它们，不猜、不替换，否则用户只是编辑学校就会静默改掉学历；清空与选择都会冒泡失焦，使档案页的自动保存对选择型字段同样成立。
- 求职策略：独立页面维护现有 `profile_preferences` 可变规则，复用档案聚合的 `preference` 和现有写接口；个人资料页不展示求职偏好内容或入口。当前匹配尚未消费这些规则，策略页须说明配置仅被保存，不表示已自动筛选职位。渠道、黑白名单和关键词过滤待明确业务规则后再设计，不扩充现有 `exclusions` 字符串数组。
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
│   │   ├── ai/                   # 模型配置（服务商/模型/凭据）与受控 LLM 调用网关
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
- 后端解释器版本为 `>=3.14`，依赖与 `backend/uv.lock` 保持一致；远端 CI、目标部署环境字体与真实大模型服务必须分别验证，本地通过不能替代这些环境的验收。
