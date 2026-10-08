# JobArk V1 数据模型设计

## 1. 状态、范围与原则

- 状态：已确认的目标设计；核心模型已有实现，本文不作为实施进度记录。设计变更须通过新增迁移与对应服务/API 变更落地，文档确认不等于代码或数据库已完成。
- 适用范围：单人本地求职工作台。V1 **不是多租户系统**，不创建 `users`、`tenants`、`owner_id` 或 `tenant_id` 等预留结构。
- 本文定义稳定的数据边界与约束；具体 API、SQLAlchemy 实现和迁移编号不在本文承诺。

### 1.1 建模原则

1. `Profile` 保存真实事实和证据，`Resume` 保存事实的可版本化表达；AI 不能直接写入事实表。
2. 用户可编辑的事实使用规范化字段；简历文档、资料修订、JD 原文/解析结果和 AI 结构化结果使用不可变 `JSONB` 快照。
3. `JobOpportunity`、`JobPosting` 与 `JobSnapshot` 分别表示职位机会、平台页面和某次内容，不能互相替代。
4. `ApplicationEvent` 是申请状态唯一历史；`Application.current_status` 仅为事件投影，不能由 HTTP 路由直接修改。
5. Dashboard 是查询投影，不保存第二份业务事实；数据量确有必要时才增加物化视图或缓存。

### 1.2 通用列与删除规则

所有表使用 `id UUID` 主键和 `created_at TIMESTAMPTZ`。可编辑实体额外有 `updated_at TIMESTAMPTZ` 与用于 API 乐观锁的 `version INTEGER NOT NULL`。时间统一按 UTC 存储。

不可变实体不提供内容更新接口：`profile_revisions`、`resume_versions`、`job_snapshots`、`job_parse_results`、`match_results`、`application_events`。它们被引用后不物理删除。

Profile 事实与证据的日常“删除”统一为归档，不因进入历史修订而禁止从当前档案移除。事实表与证据表保留 `archived_at`，归档通过乐观锁更新；默认列表、新修订、新匹配和从档案生成的新候选只使用未归档事实。历史修订、正式版本及报告仍读取自己的不可变快照，不因当前记录归档或编辑而变化。物理删除仅用于明确范围的维护操作，仍受引用检查与外键限制。

归档工作经历不静默解绑已有项目：项目保留原 `experience_id`，界面标明关联经历已归档；新建或重新关联项目不得选择已归档经历。技能名唯一性仅约束未归档技能；恢复归档技能遇到同名有效技能时返回 409，不覆盖已有记录。

除快照和分析结果外，不使用泛化 EAV 表或没有外键约束的多态关联表。需要检索、排序、约束或关联的字段必须是显式列。

## 2. 实体关系

```text
PersonalProfile ──< ProfileEvidence
       ├──────────< ProfileSkill / ProfileExperience / ProfileProject
       ├──────────< ProfileEducation / ProfileLanguage / ProfilePreference
       └──────────< ProfileRevision ──< ResumeVersion

Resume ──< ResumeVersion ──< ResumeVersionEvidence >── ProfileEvidence
   └────< ResumeDraft >── ProfileRevision（生成依据）
                └──（确认后新建，绝不覆盖）──> ResumeVersion

Company ──< JobOpportunity ──< JobPosting ──< JobSnapshot
                                 └── current_snapshot_id ──> JobSnapshot
                                                   │
JobSnapshot + ProfileRevision (+ ResumeVersion) ──< MatchResult

JobOpportunity ──< Application ──< ApplicationEvent
                         │
                         └── JobSnapshot + ResumeVersion（准备可调整，投递后锁定）

AiProvider ──< AiModel
```

## 3. Profile：事实、证据与修订

### 3.1 `personal_profiles`

单人根实体。包含姓名、联系方式、城市、简介、公开链接和 `singleton_key`。

- `singleton_key` 固定为 `default`，并施加唯一约束，保证 V1 只有一份主档案。
- 不在此表预留用户、租户或组织字段。
- 联系方式等个人信息仅在本地数据库中保存，API 日志和 AI 提示词不得无条件输出。

### 3.2 `profile_evidences`

真实信息来源，字段包括 `source_type`、`title`、`content`、`source_url`、`source_hash`、`verification_status` 和 `archived_at`。

`source_type` 初始取值：`MANUAL_DECLARATION`、`RESUME_DOCUMENT`、`WORK_PROOF`、`PROJECT_LINK`、`CERTIFICATE`、`OTHER`。证据可被多个事实复用；引用它的事实保留 `source_evidence_id` 外键。

当前证据可以编辑，但历史溯源不能只依赖可变证据 ID。资料修订与简历版本的证据声明必须冻结当时实际使用的来源摘录、内容哈希、标题、来源类型、链接和验证状态，并保留证据 ID 与证据版本号；历史读取使用冻结内容，跳转当前来源须明确标为当前记录。仅冻结实际使用的必要内容，不无条件复制整份原始简历或无关个人信息，不另建通用证据版本系统。证据归档不解绑现有事实；为仍有效的事实创建修订时，其已关联的归档来源仍须冻结并标明归档状态，新关联不得选用归档来源。

### 3.3 Profile 事实表

| 表 | 核心字段 | 关键约束 |
| --- | --- | --- |
| `profile_skills` | `profile_id`、`name`、`category`、`proficiency`、`years_of_experience`、`source_evidence_id`、`claim_status` | 同一 Profile 的未归档规范化技能名由部分唯一索引约束；无证据时必须标记为 `UNVERIFIED`。 |
| `profile_experiences` | 公司、职位、地点、开始/结束日期、职责、成果、`source_evidence_id` | 结束日期不得早于开始日期；当前经历结束日期为空。 |
| `profile_projects` | 名称、角色、描述、成果、技术栈、链接、开始/结束日期、`experience_id`、`source_evidence_id` | 工作项目与个人项目都允许；`experience_id` 可选地指向同一档案的工作经历。保留 `RESTRICT` 外键；物理删除被关联经历返回 409，日常归档不解绑项目。 |
| `profile_educations` | 学校、专业、学位、开始/结束日期、`source_evidence_id` | 学历信息只能由用户或可信证据确认。 |
| `profile_languages` | 语言、水平、说明、`source_evidence_id` | 语言水平不得被 AI 推断为已验证事实。 |
| `profile_preferences` | `profile_id`、目标地点、职位类型、薪资下限/上限/币种、远程偏好、旧 `exclusions` | `profile_id` 唯一；旧排除标签原样保留，仅供查看，不自动执行。 |

技术栈、目标地点和排除条件可使用小型 `JSONB` 数组，因为 V1 不需要跨用户统计；薪资范围、日期、状态等需要比较的字段必须使用普通列。

结构化排除策略另存 `exclusion_policies` 单人行：`rules JSONB` 中每条含稳定 ID、四类之一、原始取值与启用状态，`version` 用于乐观锁及审计引用。该数组只有 100 条上限且不需要逐条跨用户检索；`profile_preferences.exclusions` 不迁移、不自动归类。`exclusion_evaluations` 保存职位、JD 快照、规则版本、公司版本、岗位版本、结论与依据；`exclusion_exceptions` 保存同一输入版本及明确确认的原因。输入任一版本变化后旧例外失效。

### 3.4 `profile_revisions`

匹配和简历需要可复现的 Profile 输入，因此建立不可变修订表：

```text
id, profile_id, revision_no, snapshot_json, reason, created_at
UNIQUE(profile_id, revision_no)
```

在基于档案生成候选稿、创建 ResumeVersion、发起匹配或用户确认重要资料变更时确定修订；相同依据可复用已有修订，不为每次输入框保存创建修订。`snapshot_json` 必须包含当时的完整业务事实、来源证据 ID 与必要的来源冻结内容；项目包含开始/结束日期和关联经历 ID，关联经历已归档时仍保留必要的归属摘要。匹配不得只引用会继续变化的 `personal_profiles`。

快照携带结构版本，历史消费者按对应结构读取。缺失字段不能从当前事实表补入并伪装为当时内容；旧快照无法还原的来源或字段明确标为历史缺失。

## 4. Resume：表达版本与 AI 候选稿

| 表 | 核心字段 | 关键约束 |
| --- | --- | --- |
| `resumes` | 名称、目标方向、状态、`version` | 是可持续维护的一份简历方向，不是某次投递附件。 |
| `resume_versions` | `resume_id`、`version_no`、`profile_revision_id`、`document_json`、`render_schema_version`、`created_reason` | 不可变；`UNIQUE(resume_id, version_no)`。Application 只能引用此表。 |
| `resume_version_evidences` | `resume_version_id`、`evidence_id`、`source_snapshot_json` | 显式关联与当时使用的来源冻结内容一起保存，随版本不可变。 |
| `resume_drafts` | `resume_id`、`source_profile_revision_id`、`base_resume_version_id`、候选 `document_json`、`status`、`confirmed_resume_version_id`、生成元数据 | 基于档案或正式版本生成时立即固定资料修订；确认后新建 ResumeVersion，绝不覆盖旧版本。状态为 `DRAFT`、`CONFIRMED`、`DISCARDED` 或 `FAILED`。 |

`resumes` **不携带**指向 Profile 或 ProfileRevision 的外键：V1 只有一份主档案，而"这一版简历基于哪份资料修订"记录在 `resume_versions.profile_revision_id`。简历方向若绑定某个修订，就会与"长期维护、之后从新修订继续生成版本"的语义冲突；每一版的可复现性由版本自身的 `profile_revision_id` 保证。

`resume_drafts` 的字段取舍：`resume_id` 非空，候选稿始终属于某份简历方向；`base_resume_version_id` 可空，为"从零生成"的候选稿留出表达方式；`confirmed_resume_version_id` 仅在状态为 `CONFIRMED` 时非空，两者由 CHECK 约束联动，避免出现状态与产出自相矛盾的记录。`resume_version_evidences` 保留版本与证据的显式关联，不要求与 `document_json` 内的 `source_fact_id` 完全一致——前者是"这一版引用了哪些证据"的正式声明，后者是逐条内容的溯源线索。

`source_profile_revision_id` 以 `RESTRICT` 外键指向资料修订。从档案生成时固定当时修订；从正式版本优化时沿用该版本的修订，不在确认时替换为最新档案。人工空白稿尚未关联档案时允许为空，但首次引入档案事实必须确定依据，确认前必须有修订。确认生成的版本使用候选稿已记录的修订；同一事实 ID 出现在新修订中不能证明内容没有变化。更换资料依据必须显式校验引用与内容后新建候选稿，保留旧稿及其依据，不能只换外键。

`source_snapshot_json` 的证据必须属于该资料修订的来源集合，冻结内容从修订取得，不在确认时重新读取可变来源；用户增加修订外的来源时，应先建立新的明确依据。历史缺失内容不从当前证据反推补写。

## 5. Job：机会、页面与 JD 快照

当前 JD 读取不新增表或列：`latest_snapshot.posting_id` 派生当前采用来源，`latest_snapshot` 与列表 `latest_snapshot_id/latest_captured_at` 保留兼容名称及含义。列表时间称“当前 JD 首次采集”，来源 `first_seen_at` 为系统首次发现，`last_seen_at` 为系统最近接收手工保存或导入内容，不是平台扫描成功。平台发布时间未实现且不得替代。历史是去重内容集合，不是完整观察流水；历史查看、解析和申请材料选择不写 `current_snapshot_id`。无当前内容返回空，不从历史兜底。

已确认策略驱动的启动补跑／定时扫描、自动保存与自动匹配，尚未实施。策略查询快照、扫描幂等时段／租约、平台原文与人工修订区分、匹配同输入复用的建议见 `job-browsing-design.md` 第 10 节。投递策略当前缺少明确岗位检索词，不能把排除词当正向查询；匹配默认目标尚待确定。

每日平台读取目标已确认但未实施。待确认字段设计见 [job-browsing-design.md 第 9 节](job-browsing-design.md#9-每日发现与-jd-更新已确认目标与待确认设计)：平台最近成功读取时间须独立于现有混合保存语义的 last_seen_at；扫描尝试与内容快照分离，失败不推进成功时间，重复正文不新建快照。历史数据不得推断为平台读取成功。

| 表 | 核心字段 | 关键约束 |
| --- | --- | --- |
| `companies` | 名称、规范化名称、官网、历史行业文本、已确认性质代码、已确认两级行业代码、地点 | 不对规范化名称做全局唯一；历史行业文本不能自行映射为代码。外部候选不写入已确认字段。 |
| `job_opportunities` | `company_id`、职位标题、地点、雇佣类型、已确认岗位外包安排、机会状态、人工备注、去重键 | 岗位安排独立于公司性质；一个外包岗位不能改变该公司的其他岗位。 |
| `job_postings` | `opportunity_id`、`source`、`external_id`、`canonical_url`、首次/最后发现时间、页面状态、`current_snapshot_id` | 优先唯一 `(source, external_id)`；缺少外部 ID 时使用规范化 URL。当前指向必须属于本页面。 |
| `job_snapshots` | `posting_id`、`content_hash`、首次采集时间、原始 JD | 不可变；`UNIQUE(posting_id, content_hash)`，只固化内容，不承担当前指向或后续解析状态。 |
| `job_parse_results` | `job_snapshot_id`、`parser_version`、`status`、`result_json`、`failure_code` | 解析结果的唯一正式来源；PARSED 保存验证后的结果，FAILED 只保存安全错误码，不更新快照。 |

`source` 支持 `MANUAL`、`LINKEDIN`、`INDEED`、`BOSS`、`FIFTYONEJOB`；平台来源表示用户提供的详情链接，经本地内容导入产生，不代表系统已取得自动网络访问能力。V1 不保存浏览器 Cookie、登录会话或平台密码。

再次录入相同内容时复用对应快照，在同一事务中更新页面的 `current_snapshot_id`、最后发现时间及乐观锁版本；不因哈希重复返回冲突，也不修改旧快照的采集时间。因此 A → B → A 的当前内容为 A，历史仍保留 A 与 B。当前指向可在页面尚无内容时为空，存在时由数据库外键及归属约束保证指向本页面的快照。

一个机会有多个页面时，以页面最后发现时间选取当前展示来源，并以页面 ID 作并列时的稳定排序；快照首次创建时间不能代替当前观察时间。排除核验与新投递准备使用该当前内容，已有匹配及已投递申请保留原输入。

现有 `job_snapshots.parsed_json`、解析状态、解析器版本和错误码仅作历史兼容，新解析不再写这些字段。读取必须明确区分历史内嵌结果与正式 `JobParseResult`；迁移旧结果时保留原版本及来源，无法确定的内容标为历史缺失，不猜测补齐。待兼容读取与迁移验证完成后，才通过后续迁移删除旧列。`JobParseResult` 的状态与结果、错误码由 CHECK 联动：成功必须有实际结果且无错误码，失败必须无结果且有错误码；历史 JSON `null` 与 SQL `NULL` 均按无结果解释。匹配明确选择解析产物或固化自己的本地解析输出，不隐式使用“最新成功解析”。

### 5.1 平台内容导入候选

平台来源扩展为 `LINKEDIN`、`INDEED`、`BOSS`、`FIFTYONEJOB`；来源表示用户提供内容的网址平台，不宣称自动网络采集已完成。

`job_import_candidates` 保存平台与外部 ID、规范 URL、输入哈希、提取器版本、候选摘录、人工确认内容、过期时间、预览观察到的页面/版本、确认产物引用与状态。预览仅创建候选；确认后才写正式职位。确认产物只能引用正式 JobPosting/JobSnapshot，重复确认相同载荷幂等，过期、版本变化或不同载荷重确认返回冲突。跨平台不自动合并，既有机会只通过独立编辑流程修改元数据，导入只更新其页面内容。原始 HTML、Cookie 和浏览器会话不入库。详细边界见 `job-collection-design.md`。

迁移 `0012` 建立该表与平台来源约束。`target_posting_id` 与非空、正数的 `observed_posting_version` 必须配对；PENDING 不得有确认内容/产物，CONFIRMED 必须完整保存人工确认内容及产物。复合外键保证确认快照属于确认页面。接口返回固定的机会/页面/快照 ID 回执，旧候选重试不会改写当前页面，也不返回后来更新的 JD。存在候选或平台页面时拒绝降级，以保留来源和审计。

## 6. Matching：可解释且可复现的匹配

多渠道浏览的时间与报告关联缺口见 [job-browsing-design.md](job-browsing-design.md) 第 5、6 节。已确认要求区分平台发布时间、系统首次发现、最近观察与内容首次采集；当前平台发布时间尚未建模。建议发布声明归 JobPosting，MatchResult 保持不可变，由读取投影按精确输入及引擎版本判断适用性；持久化分析失败的 MatchAnalysisAttempt 是待确认建议，当前未建表。不能按机会的最新历史报告直接给当前适配结论，也不新增平行职位评分表。

`match_results` 是不可变分析记录，核心字段如下：

```text
id
job_snapshot_id
profile_revision_id
resume_version_id NULL
match_kind                 # PROFILE 或 RESUME
engine_name, engine_version
input_fingerprint
report_json                # 条件、逐字引用、证据、缺口、不确定项及解析器版本
created_at
```

约束：`match_kind = PROFILE` 时 `resume_version_id` 必须为空；`match_kind = RESUME` 时必须存在。`input_fingerprint` 用于识别完全相同输入和同一引擎版本的重复计算，但不阻止用户主动重新分析。

`report_json.requirements[].evidence` 保存每个条件关联的 Profile 事实或证据 ID、事实状态（`claim_status`）与来源标题。逐条条件的 `status` 只表达"档案里有没有这条事实"：`FACT_FOUND` 命中且该事实未挂来源记录，`EVIDENCE_ATTACHED` 命中且另挂来源记录，`UNKNOWN` 未命中（不等同于不满足）；命中与事实是否挂证据、是否为 `VERIFIED` 无关，两种命中都不得读成能力或整项条件已核实。当前字面证据引擎把 `report_json.overall_score` 固定为空，不声称技能名称出现就满足整项要求。解析结果与版本嵌入报告，独立 AI 解析产物不自动作为匹配输入。

## 7. Application：投递尝试与事件状态机

| 表 | 核心字段 | 关键约束 |
| --- | --- | --- |
| `applications` | `job_opportunity_id`、`job_snapshot_id`、`resume_version_id`、`attempt_no`、`current_status`、`material_locked_at`、`version` | 一次求职尝试；`UNIQUE(job_opportunity_id, attempt_no)`。准备阶段可调整材料，首次确认已投递后永久锁定。 |
| `application_events` | `application_id`、`sequence_no`、事件类型、前后状态、发生时间、操作者、备注、`payload_json` | 状态历史的唯一来源；`UNIQUE(application_id, sequence_no)`。 |
| `application_drafts`（后续设计，非当前表） | `application_id`、草稿类型、内容、状态、确认时间 | 问候语、筛选问题答案等候选内容；独立需求确认后再建表，当前不实现对外发送。 |

初始状态集合：`SAVED`、`PREPARING`、`READY_TO_APPLY`、`APPLIED`、`CONTACTED`、`INTERVIEWING`、`OFFERED`、`REJECTED`、`WITHDRAWN`、`CLOSED`。创建 Application 时写入首个事件；后续每次状态变更均在同一数据库事务中新增 Event 并更新 `current_status` 投影。

`SAVED`、`PREPARING` 且未锁定时允许暂未选择正式简历（`resume_version_id` 可空），但 JD 快照必须属于该机会；`READY_TO_APPLY` 必须已有正式简历版本并通过当前排除核验。准备期间更换简历或 JD 通过领域服务记录 `MATERIALS_CHANGED` 事件，包含变更前后的引用；从 `READY_TO_APPLY` 更换材料回到 `PREPARING`，重新核验，不能保留旧的就绪结论。所有变更均使用乐观锁，在同一事务更新引用、状态投影与事件。

首次人工确认已在外部完成投递时，必须明确实际使用的 JD 与正式简历版本，记录 `APPLIED` 事件并设置 `material_locked_at`；此后无论进入哪个状态，都不能替换材料或清除锁定时间。数据库 CHECK 保证就绪、锁定或进入已投递及后续结果阶段时存在正式简历版本，并保证已投递及后续结果阶段已有锁定时间；服务层禁止解锁和替换。手工补记历史使用实际旧快照，不强制改成当前 JD，也不受当前排除规则阻止；这不代表新的外部发送已获批准。

`payload_json` 采用按事件类型校验的结构，当前只承载创建时的输入引用、材料变更前后引用以及投递确认时的实际输入和确认标记，不作为无约束业务事实容器。重复保存相同材料不新增事件、不改变版本或就绪状态。事件序号按申请有序分配，不把乐观锁版本号隐式当作事件序号。未锁定便结束的尝试保留准备历史，不计为已投递。

重复申请不是静默覆盖：服务层必须显式创建下一个 `attempt_no`，并要求用户确认。

## 8. 索引、约束与迁移顺序

第一批索引只覆盖已知访问路径：

- 各子事实表的 `profile_id`、各 Job 关联表的外键、`application_events(application_id, sequence_no)`。
- `job_postings(source, external_id)`、`job_snapshots(posting_id, content_hash)`、`resume_versions(resume_id, version_no)` 和 `profile_revisions(profile_id, revision_no)` 的唯一索引。
- 职位标题、公司规范化名称与 JD 文本检索在有真实查询页面后，再根据查询计划增加 `pg_trgm` 索引；不预先给所有文本列建 GIN 索引。

建议按业务价值分迁移：

1. Profile 根、证据、事实表与 ProfileRevision。
2. Resume、ResumeVersion、ResumeDraft。
3. Company、JobOpportunity、JobPosting、JobSnapshot。
4. MatchResult。
5. Application、ApplicationEvent；ApplicationDraft 在独立需求确认后另行设计。

允许直接使用开发库检查约束、查询一致性并验证服务/API；写入验证使用事务回滚，或仅清理明确标记且由本次测试创建的记录，不清空已有业务数据。现有包含全表 `TRUNCATE` 或 `downgrade base` 的夹具不得直接指向保留业务数据的开发库。迁移先检查目标版本、影响和回退方式；升降级往返验证仅在明确可丢弃的数据范围执行，没有执行时如实记录为未验证，不把读取检查当作完整迁移验证。

已确认的归档、固定候选依据、冻结来源、当前 JD 和申请锁定边界由 `0011_confirmed_data_boundaries.py` 落实。在 `backend/` 下直接运行 `pytest`，默认共用应用配置的数据库，无需独立测试库或额外验证开关。普通 API 用例在随机 schema 与外层事务中执行，请求提交只释放保存点，退出回滚数据和 DDL。需要多连接观察提交、并发或独立迁移连接的用例使用单独的随机 schema，所有连接的搜索路径只包含该 schema，退出仅删除本次创建的 schema；不得清空或降级业务 schema。旧 `JOBARK_TEST_DATABASE_URL` 可作为连接地址覆盖，与应用 URL 相同也允许，隔离规则保持一致。CI 同样只配置一个数据库并采用上述隔离方式。

`0011` 降级只适用于尚无新语义数据的范围；有归档事实、材料事件、冻结来源、不可从旧版本推导的固定依据或重复观察后的当前指向时拒绝降级，避免静默丢失历史。

## 9. AI 模型配置

AI 配置是基础设施子域而不是业务事实，独立于 Profile/Resume/Job，只描述"用哪个模型"：

| 表 | 核心字段 | 关键约束 |
| --- | --- | --- |
| `ai_providers` | `name`、`base_url`、`api_key_ciphertext`、`api_key_mask`、`description`、`is_enabled` | 名称唯一；基地址必须为 HTTPS 或本地回环 HTTP。 |
| `ai_models` | `provider_id`、`name`、`remote_model_id`、`is_enabled`、`is_default` | `UNIQUE(provider_id, remote_model_id)`；`provider_id` 以 `CASCADE` 外键指向服务商。 |

`AiProvider 1--N AiModel`：同一服务商下的模型共享该服务商的 API Key，凭据只在服务商上保存一次。

密文边界：`api_key_ciphertext` 是应用层可逆加密（Fernet）的产物，`api_key_mask` 只是末四位展示掩码；两者都不出现在读取 API 中，明文既不落库也不返回。加密根密钥存放于数据库之外（`JOBARK_AI_CREDENTIAL_ENCRYPTION_KEY`），仅 `LOCAL` 环境允许开发默认值，`TEST`/`PROD` 缺失时拒绝敏感配置操作；根密钥更换或密文损坏时安全失败并要求重新保存 API Key，报错不包含任何凭据内容。

默认模型：`ai_models.is_default` 由**部分唯一索引** `uq_ai_models_default` 约束为全局至多一行为真，而不是只依赖服务层事务；首个保存成功的模型自动成为默认，切换默认在单个事务内完成。默认模型必须启用，且所属服务商也启用；停用或删除默认模型前必须先切换到另一个启用模型。

## 10. 资料检查、简历诊断与职位匹配

本节为已确认的设计方向，新增诊断报告尚未实现，不代表已有表、迁移或接口。第一版以可定位、可操作的问题清单为核心，不提供统一百分制总分、能力等级或招聘概率；后续维度评分须先验证标准与实际修改效果，不能把字段数量、技能数量或模型判断直接当作质量。

| 方向 | 领域所有者与输入 | 输出与保存方式 |
| --- | --- | --- |
| 个人资料检查 | Profile；当前未归档资料与必要的关联记录 | 实时计算必要信息缺漏、日期矛盾与描述待补充项；第一版不新增检查表，也不在 `personal_profiles` 上保存分数。 |
| 简历诊断 | Resume；已保存的 ResumeDraft 或不可变 ResumeVersion，以及其固定资料依据 | 输出内容缺漏、表达问题、重复项与待核对事实；需要历史回看，按下述独立报告保存，不覆盖简历正文。 |
| 职位匹配 | Matching；固定 JobSnapshot、ProfileRevision 与可选 ResumeVersion | 延续 `match_results` 的逐条件报告，保存事实依据、缺口和不确定项；不另建平行的职位评分表。 |

### 10.1 个人资料检查

检查只评价资料的可用性，不评价人的能力。联系方式不足、经历日期冲突、项目未说明本人角色等必须分别给出规则、字段位置、原因与补充动作；“影响使用”只用于确实影响特定操作的问题，其他内容标为“建议完善”或“待核对”。必填校验仍由原有服务/API 执行，检查不能绕过或替代它。

可选字段为空、没有来源证据、没有量化成果，不自动视为错误；档案未记录某项能力不等于没有能力。不同经历重叠不直接判断为虚假，个人项目不要求关联工作经历。第一版采用确定性检查，不调用模型、不增加每次失焦保存的资料修订；提示随当前资料重新计算。

### 10.2 简历诊断报告（拟新增 `resume_diagnostic_reports`）

报告属于 Resume 领域，独立于候选修改：诊断指出问题，AI 优化产生待确认修改，两者不能混为一条自动写入流程。

| 字段 | 语义与约束 |
| --- | --- |
| `id`、`created_at` | UUID 主键与 UTC 创建时间；成功报告不可变。 |
| `resume_draft_id`、`resume_version_id` | 显式外键，恰有一个非空；指向被检查的候选稿或正式版本，不使用无外键的通用目标 ID。 |
| `observed_draft_version` | 检查候选稿时必填且为正数，检查正式版本时为空；与候选稿乐观锁版本一致。 |
| `profile_revision_id` | 固定被检查简历当时的资料依据，可空；人工空白稿未建立依据时只能检查内容与表达，明确提示无法核对档案事实。不得自动改用最新档案。 |
| `input_snapshot_json`、`input_fingerprint` | 冻结实际检查的文档、检查范围、结构版本和内容哈希；候选稿会变化，仅存稿 ID 不足以复现。排除头像与无关个人信息，不复制整份原始来源文件。 |
| `engine_name`、`engine_version`、`generation_metadata` | 固定规则版本；使用模型时记录模型、提示词及输出契约版本等必要元数据，不保存密钥或上游原始错误。 |
| `report_json` | 带结构版本的问题清单、检查覆盖范围与局限；不保存总分。 |

第一版检查编辑中的候选稿前先成功保存，并以稿 ID 与预期版本发起检查；版本不一致返回 409，保存失败不能检查旧内容却声称检查了当前输入。开始时冻结输入；生成期间继续编辑不改变该报告，完成时依据候选版本或正式版本标明适用范围，已变化的稿显示“内容已变化，请重新检查”。来源外键使用 `RESTRICT`，被历史报告引用的稿、版本和修订不能物理删除；日常丢弃候选稿仍使用既有状态流转。

每项问题至少包含稳定规则/问题代码、优先级（影响使用／建议完善／表达建议）、判断来源（规则／AI）、字段路径与必要原文摘录、原因、建议动作及不确定说明。不得仅靠条目序号在已变化的稿上定位或应用修改；历史位置属于冻结输入。AI 判断不能冒充确定性错误，缺少量化成果只能建议用户补充真实信息，不能生成虚构数字。档案内容未出现只代表缺乏支撑，不能直接判定用户手写内容虚假。

报告只读，用户采取建议仍通过既有编辑与候选确认流程。确定性检查可本地完成；AI 表达诊断为可选步骤，遵守既有外发确认并明确发送范围，默认剔除整个联系方式与头像。模型失败不生成成功 AI 结论；已完成的规则报告可保留，但必须显示 AI 未完成、覆盖范围与安全错误提示。失败不创建伪成功报告；重试不能更换冻结输入而沿用旧结论。

### 10.3 针对职位的匹配与表达缺口

职位针对性分析统一归 Matching，使用第 6 节的版本化输入与现有 MatchResult，不让通用简历诊断隐式读取“当前 JD”。逐项区分：档案有事实且简历已表达、档案有事实但简历未表达、档案未记录需用户核对，以及输入不足无法判断；必须提供对应 JD 摘录、档案事实和简历位置，无法建立对应关系时保留不确定项，不猜测补齐。

字面命中、另挂来源与整项条件是否满足是不同结论，既有命中状态不能升级为能力核实。明确的硬条件与表达建议分别展示，不用平均分抵消硬条件缺口；用户自行决定是否继续准备。第一版只分析正式 ResumeVersion，候选稿的岗位分析不借用旧正式版本冒充当前内容；若后续支持候选稿，须先设计独立冻结输入与正式版本引用边界。报告不自动阻止或执行投递，不改写 Application 状态或档案事实。

## 11. 明确延后

- 用户、角色、多租户、团队共享与权限表。
- 基础 V1 不含自动投递任务；已确认后续逐次授权投递按下节独立设计。浏览器会话、验证码、Cookie 和明文外部账号凭据不作为普通业务数据入表。
- 向量、RAG、消息队列、通用审计事件和 Dashboard 物化缓存。
- 复杂公司合并、跨平台自动去重和无人工确认的重复申请。

这些能力出现真实需求时，必须先增加 ADR 和对应的迁移设计，不能以“预留字段”形式提前进入 V1 表结构。

## 12. 三阶段扩展：数据设计建议，未实施

稳定范围见[分阶段需求](requirements/job-intake-and-submission.md)，信任边界见[ADR 0006](adr/0006-职位获取与确认投递的信任边界.md)，字段／约束／时间／迁移细节以[详细设计第3、4、6节](job-intake-and-submission-design.md)为主。此前第5、6、11节描述基础模型／延期范围，不表示后续能力永久禁止，也不表示以下表已经存在。

| 阶段 | 复用及必要补充建议 | 不能由现有字段代替的原因 |
| --- | --- | --- |
| 一 | Opportunity允许未知company/title、Company.field_sources、job_observations正式保存记录 | 假的未知公司污染事实；updated_at或快照不能表示来源修订与重复观察。Company.name仍必填，旧数据不改写。 |
| 二 | 观察扩展平台尝试、Posting成功读取／用户保存／保护及平台候选指针、collection_runs、match_analysis_attempts、MatchResult可选parse引用 | 内容版本不等于尝试历史；last_seen_at继续是接受内容时间；内存任务不足以恢复重启与分析失败。 |
| 三 | submission_plans、submission_tasks、submission_attempts；ApplicationEvent新增审计种类 | 需冻结实际附件字节与字段、逐次授权、发送边界和未知结果；求职状态不能表示排队／核实。 |

保留current_snapshot_id与last_seen_at DESC、posting.id DESC默认规则，保护人工采用内容时自动候选不推进接受时间／当前指针；A→B→A旧捕获时间不变。新冲突来源可暂无接受时间，不进入默认选取。平台日期声明带原文／精度／来源观察，读投影显示，不用系统时间回填。跨平台／同名公司不自动合并；历史观察上线前未记录的明确缺失。

按阶段新建迁移，不重写0011–0013，不提前建所有未来表；新增FK／唯一键／材料锁与响应类型同批变更。测试升降级及多连接仅在随机schema，业务库应用另行授权；降级遇到不可兼容的新记录拒绝静默丢失。本文没有授权执行任何迁移或保存平台会话。

## 2026-10-07 分析范围修订

本轮以 [JD 分析正式需求](requirements/jd-analysis.md) 和 ADR 0007 为准。允许新 schema 的可解释 10 分参考区间；旧 overall_score 保持 null，不回填。未知不计零，硬限制优先，禁止录用概率、无依据总分和自动淘汰。JobOpportunity.company_id/title 可空，Company.name 仍必填，不建占位公司。ProfilePreference 增加有版本的目标方向、显式硬限制口径和优先名单；旧偏好不升级为硬限制。MatchResult 增加可空成功解析引用，报告 JSON 冻结必要策略、条件与算法/模型版本并记录内容指纹。公司公开报告及来源归 Job，独立不可变，不改变确认分类或能力分。外发确认和事务边界沿用既有约束；自动采集、调度、外部投递不在本轮实现范围。本文是后续范围决策，不是实现或真实运行验收声明。

## 2026-10-07 JD 可靠性增量

迁移 0017：profile_educations 新增可空 degree_level（HIGH_SCHOOL/ASSOCIATE/BACHELOR/MASTER/DOCTOR/OTHER）及 study_mode（FULL_TIME/PART_TIME/OTHER），旧 degree 原文不修改。结构化学历只来自用户确认，不自动拆分历史文本；导入预览不采用模型猜测，用户补录转本人陈述。新字段进入 ProfileRevision，修改仍按既有内容归因规则执行。

profile_preferences 新增 role_keywords JSONB 默认 []、acceptable_salary_min 可空非负整数。target_roles 表示意愿，role_keywords 表示补充线索；期望 salary_min/max 与最低可接受月薪不同，独立底线不得高于期望下限。原硬薪资限制未设置独立底线时继续以 salary_min 比较。学习形式、底线、技术栈与工作关联不自动填写。

JobParseResult.result_json 增加 admission_status、source_start/end、relation/group_id、experience_subject；保留旧解析兼容。MatchResult 继续 report schema jd-analysis-v2，通过 scoring/prompt/parser 版本区分计算逻辑，新增事实 fact_quotes、source_support 与 data_warnings。不新增报告表或修改历史报告。0017 新字段已有数据时拒绝 downgrade，空值时可退回 0016。
