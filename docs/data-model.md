# JobArk V1 数据模型设计

## 1. 状态、范围与原则

- 状态：已确认，待按领域分阶段实施。
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

不可变实体不提供内容更新接口：`profile_revisions`、`resume_versions`、`job_snapshots`、`match_results`、`application_events`。它们被引用后不物理删除。对正在被版本、匹配或申请引用的 Profile 事实与证据，界面的“删除”应执行归档或返回冲突错误，并说明引用位置。

除快照和分析结果外，不使用泛化 EAV 表或没有外键约束的多态关联表。需要检索、排序、约束或关联的字段必须是显式列。

## 2. 实体关系

```text
PersonalProfile ──< ProfileEvidence
       ├──────────< ProfileSkill / ProfileExperience / ProfileProject
       ├──────────< ProfileEducation / ProfileLanguage / ProfilePreference
       └──────────< ProfileRevision ──< ResumeVersion

Resume ──< ResumeVersion ──< ResumeVersionEvidence >── ProfileEvidence
   └────< ResumeDraft ──（确认后新建，绝不覆盖）──> ResumeVersion

Company ──< JobOpportunity ──< JobPosting ──< JobSnapshot
                                                   │
JobSnapshot + ProfileRevision (+ ResumeVersion) ──< MatchResult

JobOpportunity ──< Application ──< ApplicationEvent
                         │
                         └── JobSnapshot + ResumeVersion + ApplicationDraft
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

### 3.3 Profile 事实表

| 表 | 核心字段 | 关键约束 |
| --- | --- | --- |
| `profile_skills` | `profile_id`、`name`、`category`、`proficiency`、`years_of_experience`、`source_evidence_id`、`claim_status` | 同一 Profile 的同一规范化技能名唯一；无证据时必须标记为 `UNVERIFIED`。 |
| `profile_experiences` | 公司、职位、地点、开始/结束日期、职责、成果、`source_evidence_id` | 结束日期不得早于开始日期；当前经历结束日期为空。 |
| `profile_projects` | 名称、角色、描述、技术栈、链接、开始/结束日期、`source_evidence_id` | 工作项目与个人项目都允许，不强制绑定工作经历。 |
| `profile_educations` | 学校、专业、学位、开始/结束日期、`source_evidence_id` | 学历信息只能由用户或可信证据确认。 |
| `profile_languages` | 语言、水平、说明、`source_evidence_id` | 语言水平不得被 AI 推断为已验证事实。 |
| `profile_preferences` | `profile_id`、目标地点、职位类型、薪资下限/上限/币种、远程偏好、排除条件 | `profile_id` 唯一；偏好是可变规则，不属于履历事实。 |

技术栈、目标地点和排除条件可使用小型 `JSONB` 数组，因为 V1 不需要跨用户统计；薪资范围、日期、状态等需要比较的字段必须使用普通列。

### 3.4 `profile_revisions`

匹配和简历需要可复现的 Profile 输入，因此建立不可变修订表：

```text
id, profile_id, revision_no, snapshot_json, reason, created_at
UNIQUE(profile_id, revision_no)
```

仅在创建 ResumeVersion、发起匹配或用户确认重要资料变更时创建修订，而不是每次输入框保存都创建。`snapshot_json` 必须包含当时的事实内容和来源证据 ID；匹配不得只引用会继续变化的 `personal_profiles`。

## 4. Resume：表达版本与 AI 候选稿

| 表 | 核心字段 | 关键约束 |
| --- | --- | --- |
| `resumes` | 名称、目标方向、状态、`version` | 是可持续维护的一份简历方向，不是某次投递附件。 |
| `resume_versions` | `resume_id`、`version_no`、`profile_revision_id`、`document_json`、`render_schema_version`、`created_reason` | 不可变；`UNIQUE(resume_id, version_no)`。Application 只能引用此表。 |
| `resume_version_evidences` | `resume_version_id`、`evidence_id` | 保留简历版本和真实证据的显式关联。 |
| `resume_drafts` | `resume_id`、`base_resume_version_id`、候选 `document_json`、`status`、`confirmed_resume_version_id`、生成元数据 | AI 输出状态为 `DRAFT`、`CONFIRMED`、`DISCARDED` 或 `FAILED`；确认后新建 ResumeVersion，绝不覆盖旧版本。 |

`resumes` **不携带**指向 Profile 或 ProfileRevision 的外键：V1 只有一份主档案，而"这一版简历基于哪份资料修订"记录在 `resume_versions.profile_revision_id`。简历方向若绑定某个修订，就会与"长期维护、之后从新修订继续生成版本"的语义冲突；每一版的可复现性由版本自身的 `profile_revision_id` 保证。

`resume_drafts` 的字段取舍：`resume_id` 非空，候选稿始终属于某份简历方向；`base_resume_version_id` 可空，为"从零生成"的候选稿留出表达方式；`confirmed_resume_version_id` 仅在状态为 `CONFIRMED` 时非空，两者由 CHECK 约束联动，避免出现状态与产出自相矛盾的记录。`resume_version_evidences` 保留版本与证据的显式关联，不要求与 `document_json` 内的 `source_fact_id` 完全一致——前者是"这一版引用了哪些证据"的正式声明，后者是逐条内容的溯源线索。

## 5. Job：机会、页面与 JD 快照

| 表 | 核心字段 | 关键约束 |
| --- | --- | --- |
| `companies` | 名称、规范化名称、官网、行业、地点 | 不对规范化名称做全局唯一，避免同名公司被错误合并。 |
| `job_opportunities` | `company_id`、职位标题、地点、雇佣类型、机会状态、人工备注、去重键 | 表示一个真实职位机会，不等于招聘 URL；去重结论必须可人工纠正。 |
| `job_postings` | `opportunity_id`、`source`、`external_id`、`canonical_url`、首次/最后发现时间、页面状态 | 优先唯一 `(source, external_id)`；缺少外部 ID 时使用规范化 URL。 |
| `job_snapshots` | `posting_id`、`content_hash`、抓取时间、原始 JD、`parsed_json`、解析状态、解析器版本、安全错误码 | 不可变；`UNIQUE(posting_id, content_hash)`。解析失败仍保留原始 JD，且不写入伪造结构化字段。 |

`source` 初始支持 `MANUAL`；后续平台适配器再按真实能力增加来源值。V1 不保存浏览器 Cookie、登录会话或平台密码。

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
overall_score NULL
hard_constraints_json
dimension_scores_json
evidence_json
gaps_json
uncertainties_json
status, failure_code
created_at
```

约束：`match_kind = PROFILE` 时 `resume_version_id` 必须为空；`match_kind = RESUME` 时必须存在。`input_fingerprint` 用于识别完全相同输入和同一引擎版本的重复计算，但不阻止用户主动重新分析。

`evidence_json` 至少保存每个结论关联的 Profile 事实或证据 ID、说明和置信状态。`overall_score` 只能是摘要，不能成为唯一输出；AI 或解析失败时创建失败记录或返回错误，不产生貌似有效的分数。

## 7. Application：投递尝试与事件状态机

| 表 | 核心字段 | 关键约束 |
| --- | --- | --- |
| `applications` | `job_opportunity_id`、`job_snapshot_id`、`resume_version_id`、`attempt_no`、`current_status`、`version` | 一次求职尝试；`UNIQUE(job_opportunity_id, attempt_no)`。 |
| `application_events` | `application_id`、`sequence_no`、事件类型、前后状态、发生时间、操作者、备注、`payload_json` | 状态历史的唯一来源；`UNIQUE(application_id, sequence_no)`。 |
| `application_drafts` | `application_id`、草稿类型、内容、状态、确认时间 | 问候语、筛选问题答案等候选内容；确认前不代表外部已发送。 |

初始状态集合：`SAVED`、`PREPARING`、`READY_TO_APPLY`、`APPLIED`、`CONTACTED`、`INTERVIEWING`、`OFFERED`、`REJECTED`、`WITHDRAWN`、`CLOSED`。创建 Application 时写入首个事件；后续每次状态变更均在同一数据库事务中新增 Event 并更新 `current_status` 投影。

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
5. Application、ApplicationEvent、ApplicationDraft。

每个迁移必须在独立 PostgreSQL 测试库执行 `upgrade head → downgrade base → upgrade head`；不得对开发库运行降级验证。

## 9. 明确延后

- 用户、角色、多租户、团队共享与权限表。
- 自动投递任务、浏览器会话、验证码、Cookie 与外部平台账号数据。
- 向量、RAG、消息队列、通用审计事件和 Dashboard 物化缓存。
- 复杂公司合并、跨平台自动去重和无人工确认的重复申请。

这些能力出现真实需求时，必须先增加 ADR 和对应的迁移设计，不能以“预留字段”形式提前进入 V1 表结构。
