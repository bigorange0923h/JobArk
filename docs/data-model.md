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

| 表 | 核心字段 | 关键约束 |
| --- | --- | --- |
| `companies` | 名称、规范化名称、官网、历史行业文本、已确认性质代码、已确认两级行业代码、地点 | 不对规范化名称做全局唯一；历史行业文本不能自行映射为代码。外部候选不写入已确认字段。 |
| `job_opportunities` | `company_id`、职位标题、地点、雇佣类型、已确认岗位外包安排、机会状态、人工备注、去重键 | 岗位安排独立于公司性质；一个外包岗位不能改变该公司的其他岗位。 |
| `job_postings` | `opportunity_id`、`source`、`external_id`、`canonical_url`、首次/最后发现时间、页面状态、`current_snapshot_id` | 优先唯一 `(source, external_id)`；缺少外部 ID 时使用规范化 URL。当前指向必须属于本页面。 |
| `job_snapshots` | `posting_id`、`content_hash`、首次采集时间、原始 JD | 不可变；`UNIQUE(posting_id, content_hash)`，只固化内容，不承担当前指向或后续解析状态。 |
| `job_parse_results` | `job_snapshot_id`、`parser_version`、`status`、`result_json`、`failure_code` | 解析结果的唯一正式来源；PARSED 保存验证后的结果，FAILED 只保存安全错误码，不更新快照。 |

`source` 初始支持 `MANUAL`；后续平台适配器再按真实能力增加来源值。V1 不保存浏览器 Cookie、登录会话或平台密码。

再次录入相同内容时复用对应快照，在同一事务中更新页面的 `current_snapshot_id`、最后发现时间及乐观锁版本；不因哈希重复返回冲突，也不修改旧快照的采集时间。因此 A → B → A 的当前内容为 A，历史仍保留 A 与 B。当前指向可在页面尚无内容时为空，存在时由数据库外键及归属约束保证指向本页面的快照。

一个机会有多个页面时，以页面最后发现时间选取当前展示来源，并以页面 ID 作并列时的稳定排序；快照首次创建时间不能代替当前观察时间。排除核验与新投递准备使用该当前内容，已有匹配及已投递申请保留原输入。

现有 `job_snapshots.parsed_json`、解析状态、解析器版本和错误码仅作历史兼容，新解析不再写这些字段。读取必须明确区分历史内嵌结果与正式 `JobParseResult`；迁移旧结果时保留原版本及来源，无法确定的内容标为历史缺失，不猜测补齐。待兼容读取与迁移验证完成后，才通过后续迁移删除旧列。`JobParseResult` 的状态与结果、错误码由 CHECK 联动：成功必须有实际结果且无错误码，失败必须无结果且有错误码；历史 JSON `null` 与 SQL `NULL` 均按无结果解释。匹配明确选择解析产物或固化自己的本地解析输出，不隐式使用“最新成功解析”。

## 6. Matching：可解释且可复现的匹配

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

已确认的归档、固定候选依据、冻结来源、当前 JD 和申请锁定边界由 `0011_confirmed_data_boundaries.py` 落实。开发库 API 回归可在 `backend/` 下设置 `JOBARK_VERIFY_DEVELOPMENT_DATABASE=1` 后运行 `pytest`：每个用例在同一开发库连接中创建随机 schema，搜索路径仅包含该 schema；请求提交只释放保存点，外层事务最终回滚数据和 DDL。无需独立测试库。迁移升降级往返由 `tests/test_development_boundaries.py` 在同样的事务范围验证。仍依赖旧破坏性夹具的直接数据库测试可跳过；该夹具禁止使用开发库连接串。

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

## 10. 明确延后

- 用户、角色、多租户、团队共享与权限表。
- 自动投递任务、浏览器会话、验证码、Cookie 与外部平台账号数据。
- 向量、RAG、消息队列、通用审计事件和 Dashboard 物化缓存。
- 复杂公司合并、跨平台自动去重和无人工确认的重复申请。

这些能力出现真实需求时，必须先增加 ADR 和对应的迁移设计，不能以“预留字段”形式提前进入 V1 表结构。
