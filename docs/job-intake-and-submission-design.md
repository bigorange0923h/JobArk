# 职位录入、辅助采集与确认后投递：实施设计

## 1. 结论、证据与适用范围

结论：三阶段方向可以采用，但须调整“公司未知仍可录入评估”“人工内容保护”“具体发送授权及结果未知”三个实现边界。先把复制 JD 的本地闭环做好，采集与提交按平台能力独立开关，任一外部能力不可用时保留本地工作台。

[需求](requirements/job-intake-and-submission.md)定义已确认范围；[ADR 0006](adr/0006-职位获取与确认投递的信任边界.md)定义稳定信任边界；[代码基线](reviews/2026-10-06-job-intake-and-submission-baseline.md)区分真实实现和静态检查；[Issue 正文](implementation/job-intake-and-submission-issues.md)提供实施拆分。本文所有新增表、字段、接口、阈值和控件组合均为**本次设计建议，尚未实现**，不能当作已批准迁移或平台可用性声明。

已确认但未实现：单平台策略搜索、启动检查、每小时执行、有效结果自动保存与匹配；查看实际材料后逐次授权的辅助投递。首个平台沿用 FIFTYONEJOB。已实现手工渠道／公司介绍、本地内容导入、显式当前 JD、固定分析输入、事件化人工申请；详情见代码基线。现有技能字面检索不等于完整硬条件审核。

### 1.1 反方检验

| 核心假设／反例 | 结论与应对 |
| --- | --- |
| 缺公司资料不影响评估，但公司名和 Company 外键必填 | 当前不成立。建议允许未知公司／标题的 JD-only 保存；不创建假的“未知公司”实体。 |
| 自动读取后只保护被编辑来源即可 | 不成立。另一来源 last_seen_at 变新会抢走机会默认内容；保护范围必须覆盖机会当前采用的人工内容。 |
| 一个唯一任务和点击成功即可证明只投一次 | 不成立。发送后进程崩溃可能平台已收、本地未知；禁止重新派发，先核实。 |
| 用户已登录，四站页面解析测试通过，就能自动化 | 不成立。许可、搜索入口、完整性、会话、回执各自验证；缺一项关闭相应能力。 |
| 手工和平台同名岗位必然同一机会 | 不成立。外包、重发和同名公司会误合并；不自动跨源合并，无链接记录保持独立。 |
| 公司介绍充分即可由 AI 分类为事实 | 不成立。平台声明、用户陈述、规则建议和已确认分类分开；未知保留未知。 |

不推荐为了采集先建立通用调度／事件总线／公司事实图谱。不承诺外部恰好执行一次、匹配总分或投递成功率。合理部分成立的条件是：复制输入始终可用、领域事实落库、外部操作按能力和授权隔离。

## 2. 用户流程与页面契约

复用 JobList、JobDetail、Matching、求职策略和 Application 页面及 Ant Design Vue／主题令牌。只在已有页面增加表单分组、抽屉和任务详情，不新增平行职位库或导航。

| 入口／步骤 | 交互、数据和退出规则 |
| --- | --- |
| 职位列表「复制 JD」 | 原文必填；常用渠道／自定义渠道；来源链接选填。公司名／标题／公司介绍等可空。手工渠道保持 MANUAL，不假称平台已核实。取消本轮编辑不写库。 |
| 「提取并核对」 | 默认本地提取确定信息，不调用平台。原文与候选并排，标出来源摘录、未知、冲突及用户改写。没有可提取项显示“请补充，可直接保存 JD”；人工填写不附虚假摘录。AI 为可选操作，按钮旁展示实际外发范围与默认模型，点击即确认外发，不另加勾选及重复弹窗。 |
| 补充公司 | 明确识别的信息只填仍未编辑的空字段；可搜索选取已有公司，用户明确选中后关联。没有结果可手写或保持缺失。导入失败保留 JD，允许复制公司介绍。选择已有公司不自动覆盖其资料。 |
| 「保存并评估」 | 保存原文、来源与人工字段原子提交；成功后进入详情，再解析／评估。保存成功分析失败显示“已保存，分析未完成”，重试分析不再新建职位。档案修订不存在时给出建立资料入口，JD 仍保存成功。 |
| 职位详情 | 延续独立「当前保存 JD」和历史区，展示采用来源、原链接／无链接、首次发现、最近接受、该内容首次采集；未来增加独立平台读取成功与平台声明日期。明确不是实时最新。选历史只改变查看／分析对象；默认变化提示用户，保留其主动选择。无当前内容不拿任意历史兜底。 |
| 「评估」 | 固定快照、档案修订和可选正式简历。分开展示硬条件摘录、档案依据、证据状态、缺口、未知和简历表达问题；说明覆盖维度。解析失败可看原文；失败不展示“没有问题”。历史报告标明输入和引擎版本，禁止新旧报告静默混合。 |
| 申请「准备材料」 | 延续 Application 明确选择快照与正式简历。候选稿先按现有规则确认成正式版本。新增实际提交清单抽屉：目标平台／账号标签、JD 版本、实际附件预览／哈希、线上简历字段、问候语、回答、缺项、模型外发提示。自动提交不支持则显示下载／复制／打开平台。 |
| 「确认发送这些材料」 | 清单展示后一次明确确认创建任务，既有 exclusion 准备核验／输入绑定例外不绕过。与「记录已在平台投递」分开。缺材料、目标或可用能力时不能确认；已授权后内容变化显示授权失效及新清单。 |
| 申请任务区域 | 展示排队、检查、待人工、发送、核实、成功、失败及 request_id；人工接管打开原链接，不发送任意新内容。结果未知醒目说明可能已发送，提供只读核实和人工历史记录，不出现直接“再投一次”。 |
| 求职策略 | 复用城市／排除规则，新增正向搜索关键词、单平台启用及采集预算；既有“预览判定”仍只是已保存规则对已保存职位的判定，不是搜索或匹配报告。先显示能力不可用及原因，不做无数据成功提示。 |

共同状态：首次加载骨架；合法无数据展示具体补充入口；请求失败显示安全文案、重试与 request_id；有旧数据保留并标注“刷新失败”；未知时间显示“未知／尚未记录”。字段 422 就地定位不清空原文；409 保留草稿并展示服务器最新版本供人工重新核对，不自动覆盖或盲重试；保存／确认按钮忙碌时禁重复。原文、换行和长链接不能截断保存。窄窗口分组纵向排列，长原文折行、表格内滚动、抽屉与主按钮可触达；保持键盘焦点和读屏标签。离开未保存表单只在确有草稿时提醒；不增加每一步确认弹窗。默认不把敏感 JD／简历持久化到 localStorage；跨会话草稿恢复另行确认范围。

## 3. 数据职责与最小扩展

### 3.1 现有实体继续使用

| 实体／所有者 | 职责和不可混淆的边界 |
| --- | --- |
| Company／Job | 可编辑公司资料及明确确认分类，名称非唯一身份；平台声明不等于独立验证。 |
| JobOpportunity／Job | 一次逻辑岗位机会；多来源聚合、人工备注与分类。不等于每个 URL，也不是申请。 |
| JobPosting／Job | 渠道页面身份、稳定平台 ID／链接、当前采用快照；MANUAL 无链接也有效。source 是身份命名空间，channel_name 是用户声明。 |
| JobSnapshot／Job | 同一 posting 内按 hash 去重的不可变 JD 原文；captured_at 是内容首次出现。重复观察 A→B→A 不新增 A，不更改其首次时间。 |
| JobParseResult／Job | 固定 JD 的成功／失败解析版本和摘录，原文独立。 |
| MatchResult／Matching | 固定 JD、资料修订、可选正式简历与报告引擎的不可变条件对照；不存未经校准总分。 |
| Application／Application | 一次求职尝试，准备材料、已投递材料锁、求职状态投影。 |
| ApplicationEvent／Application | 有序、不可变的材料／求职状态／提交审计事件；状态只由事件事务更新。 |

### 3.2 阶段一建议

1. **JD-only**：JobOpportunity.company_id、title 可空，Company.name 仍必填；POST /jobs 中公司／标题可选，raw_jd 必填。所有读取模型、前端、Dashboard 和策略判断同步可空契约。界面“公司未提供”“标题未提供”只是展示占位，不入库作为事实。公司规则缺输入产生 REVIEW，不阻止解析及评估；准备发送仍执行具体目标和策略核验。旧行不回填或删改，已有有效请求兼容。
2. Company 增加 `field_sources` JSONB（结构版本、每字段 origin、来源 URL／观察 ID、必要摘录、哈希、记录时间及人工清空标记），复用 Company.version；公司已知标量字段不新增副本表。人工修订须冻结修改前后值与来源到对应观察／审计，历史报告保留其冻结输入。来源引用指向存在的记录、不可任意跨公司；摘录／值一致性由服务验证，不把 JSON 当作免校验外键。旧数据标 LEGACY_UNKNOWN，不推断渠道、作者或观察时间。
3. **job_observations**：记录每次正式保存／确认更新，阶段二扩展为每次平台获取尝试。最低字段见下一节；历史不补造观察，幂等重复确认返回旧回执不产生新观察。

为何不用更简单方式：假的“未知公司”会制造身份与错误合并；仅让前端预览 JD 而不能保存评估，会另建无快照分析链；仅使用 captured_at／updated_at 无法区分重复内容和失败。优先一个可空关联与小型来源 JSON，而非公司事实、冲突、来源各一张表。

粘贴核对使用无持久化新表的 intake-preview；已有 job_import_candidates 保留平台身份、版本、24 小时和确认回执约束。无链接复制 JD 不硬塞进该平台候选表。预览返回输入哈希和逐字段摘录，保存重新校验引用；超出摘录的修改改标 MANUAL。

输入沿用现有JD最多100,000字符、用户提供内容UTF-8最多1MiB、渠道最多80字符、公司介绍最多10,000字符；链接限制合法HTTPS／允许的用户可见渠道链接，不替手工无链接创建虚假URL。提取候选逐字段返回value、origin、quote及原文偏移，quote必须是对应JD或明确公司原文的逐字子串；内容哈希不符重新提取，不将旧摘录关联新原文。只有可准确建立来源的值才预填，规范化不改变原文。公司官网／介绍链接不得由服务无约束访问（SSRF），自动访问只走获准适配器白名单。

### 3.3 观察与时间：建议字段和约束

| 记录 | 建议字段／约束 |
| --- | --- |
| job_observations | UUID；method=`MANUAL_SAVE/CONTENT_IMPORT/AUTO_READ`；operation_key 唯一；posting_id、snapshot_id 可空，但 snapshot 存在必须有对应 posting，以复合外键保证归属；company_id 可空明确 FK；collection_run_id 可空 FK；candidate_id 可空唯一 FK。started_at、finished_at；outcome=`STARTED/ACCEPTED/READ_OK/CONFLICT/FAILED/INTERRUPTED`；adopted 布尔；提取器版本、原始必要字段／公司候选和人工修改、内容哈希、脱敏安全错误码、request_id、平台日期声明。 |
| JobPosting 阶段二补充 | last_platform_success_at、last_platform_snapshot_id（归属约束）、last_user_saved_at；selection_mode=`AUTO/MANUAL_PROTECTED/LEGACY_PROTECTED`。缺失均可空，不回填为真实读取时间。 |
| 平台发布时间 | 保存在成功观察的日期声明结构：raw、value、precision=`INSTANT/DATE/TEXT/UNKNOWN`、时区依据、source_quote、声明类型（发布／更新）。只有明确可校验时解析，日期不能捏造时分秒；聚合显示最新可靠声明并可追溯观察，不覆盖旧声明或快照 captured_at。 |

平台 STARTED 先短事务持久化，网络在事务外，完成时 CAS 写终态；终态不可修改。崩溃后过期 STARTED 标 INTERRUPTED，由只读任务新建重试观察。成功 JD／公司候选／指针推进在短事务内原子提交；失败只留下尝试，不创建空职位。内容完整但公司提取失败可 READ_OK，company_warning 单独保存。

时间定义：first_seen_at 保持系统首次发现；last_seen_at 保持系统最后**接受为当前内容**的时间，不能悄悄改成扫描成功时间；last_user_saved_at 记录正式用户保存；last_platform_success_at 只有真实完整 JD 读取成功才更新（即使冲突未采用）；captured_at 永不随重复读取变化；平台发布是来源声明。新发现未采用的冲突来源 last_seen_at 在新 schema 中允许为空、不能进入当前选择；默认查询只取合法 current_snapshot_id 和非空 last_seen_at。旧行不改含义。未知列的 UI 明确“历史未记录”。

### 3.4 更新、去重、公司来源与人工保护

- 当前规则保留：每个 posting 显式指针；机会默认 last_seen_at DESC、posting.id DESC，不按 captured_at 或历史数组首项。A→B→A 采用 A 时只推进接受时间和指针。
- 同平台同 stable ID 或严格规范 URL 可复用 posting；两者命中不同已有行返回 IDENTITY_CONFLICT，不猜哪个正确。平台无稳定身份仅保留获取尝试／待人工候选，不自动入库。
- 同名公司／同标题／相似 JD／渠道文本都不是跨平台唯一键。不同来源自动发现默认独立机会；已存在显式聚合来源照常使用，不开展人工合并功能。手工无链接与后续平台结果仅给比较提示，不自动绑定。未来关联须单独设计，禁止搬动有 Application/MatchResult 引用的 posting 造成材料归属失效。
- 自动读取只更新平台候选与可允许采用的 JD；标题、公司、分类、备注的人工非空值及 MANUAL_CLEARED 不覆盖。可靠平台信息可填来源明确的空字段，先检查 Company.version 与人工保护；冲突保留候选让用户核对，不静默解决。公司相同名称不复用已有 Company，用户可明确选现有公司并记录关联。
- 人工编辑 JD 将该来源设 MANUAL_PROTECTED。在机会锁内查询当前采用来源：若它为 MANUAL_PROTECTED 或 LEGACY_PROTECTED，该机会任何自动来源都只保存候选，不推进 adopted 指针及 last_seen_at；防止另一来源抢走人工默认。遗留内容保守保护，单个平台新自动记录为 AUTO。
- 「采用平台内容并允许后续更新」携带 observation、候选 snapshot、posting.version 和机会当前来源指纹；短事务 CAS，展示会替换的当前内容。核对后新观察出现返回409重新核对。只影响采用与保护模式；普通历史查看／解析不调用此写接口。

### 3.5 兼容与未来迁移

不重写 0011–0013；实施时分阶段新 Alembic。阶段一放宽机会空关联、增加来源与保存观察；阶段二补读取字段／保护模式、run／分析尝试；阶段三才建提交表。数据库约束、schema、OpenAPI 中文说明、前端类型同一交付更新。兼容 latest_snapshot/latest_captured_at 且不改旧语义；新增字段可空，旧请求和报告可读。历史观察显示“该功能上线前未记录”，不从快照数量推导观察次数。

迁移前检查实际 revision、空值消费者和约束影响；只在 UUID 随机 schema 验证升降级／并发，多连接均不含 public 搜索路径。业务库迁移另行授权，不在本次设计执行。降级有新观察、未知公司机会、已授权材料或提交证据时拒绝丢失数据的回退；提前验证新增 NOT NULL／外键不会误伤遗留记录。没有真实部署证据不声称已迁移。

## 4. 解析与投递评估

复用 Matching，不引入平行评分。增加 report schema／engine_version，旧报告不改写。推荐 `MatchResult.parse_result_id` 可空 FK，存在时必须 PARSED 且属于选定快照；用户选历史解析时固定它，未选则明确本地默认版本，不在后台换 AI 产物。快照原文逐字引用仍是锚点。

每条条件包含 condition_id、类别、硬性声明及其摘录、事实证据引用／状态、覆盖范围和未知原因。档案结论（FACT_FOUND／PROFILE_NOT_RECORDED／NOT_EVALUATED）与简历表达（EXPRESSED／MISSING／UNRESOLVED／NOT_APPLICABLE）分别输出；字面命中不等于满足能力。无证据的用户技能可用但不称独立核实。学历／经验等先做支持范围内的确定性核对，难以比较的学历表述、重叠经历／行业年限和语义条件均留未知，不以技能命中代替。职责与硬要求分开，不把每行都标门槛。

Resume Match 固定正式版本及其同一 ProfileRevision，报告给出简历具体位置；档案有事实、简历无关联不应变成“档案没有”。无法建立文字／事实映射显示 UNRESOLVED。表达建议是候选，改稿走 Resume 已有流程。MatchResult 不自动拒绝用户继续准备；准备阶段排除规则及例外确认沿用既有机制。

阶段二增加 Matching-owned `match_analysis_attempts`：固定 snapshot/revision/resume/parse/engine fingerprint、state、request_id、安全错误、开始／结束时间、可空 result_id；活跃 fingerprint 唯一。它记录自动分析失败／输入不足和重启恢复，成功可复用已有不可变报告，不在 MatchResult 填伪成功。若阶段一无后台触发，不提前建此表。自动默认 Profile Match；Resume Match 仅显式配置同修订正式版本，否则跳过并说明。没有可用 ProfileRevision 不经 GET 隐式生成，需由 Profile 所有者在明确保存流程固化依据。

## 5. 自动采集与调度

### 5.1 能力验证门槛

先验证 FIFTYONEJOB，依据记录见[官方资料基线](reviews/2026-10-06-job-intake-and-submission-baseline.md)。未证明许可、稳定访问及适用条款，不启用真实操作。能力矩阵逐项记录证据日期、版本、范围、限制与有效期：READ_SEARCH、READ_DETAIL、READ_COMPANY、READ_FORM、SUBMIT、READ_RECEIPT；后两项不从读能力推导。只允许官方明确可用方式或经确认获准的页面操作，不开发平台内部接口、token 获取或绕验证。

建议小样本验证不同详情结构、完整正文、公司信息缺失、重复／失效岗位、登录续期和许可频率；再以获准预算连续观察至少一周，记录实际成功／失败与变化类型，不能用模拟吞吐量宣称平台成功率。样本周期是建议，不替代平台要求。允许读详情不允许搜索时降级为用户指定链接更新；公司能力失败不阻断 JD；提交无可靠回执保持人工。扩展平台须复做矩阵和真实验收，不能只加 enum。

### 5.2 适配器契约

建议端口位于 automation，业务持久化仍属 Job/Matching/Application；先复用已有纯内容解析器。

| 操作 | 输入 | 输出／约束 |
| --- | --- | --- |
| capabilities | 平台、运行环境 | 有效能力／限制／版本，不执行采集或返回秘密。 |
| search | 固定正向策略、游标、预算、session_handle | stable ID／规范 URL 候选、下一游标、安全警告；不直接造 Company/Opportunity。 |
| read_detail/read_company | 已校验平台身份、超时、session_handle | 原文／提取字段、逐字来源、发布时间声明、observed_at、提取器版本及完整性；公司抓取独立失败可保留 JD。 |
| inspect_form | 具体目标及会话、只读权限 | 表单版本／必需字段／可见默认值／已申请基线；不提前上传个人材料。 |
| execute_manifest | 已授权固定 manifest、任务 fence、session_handle | 步骤／发送边界、可靠回执或明确安全失败／结果未知；不能自由改字段或追加 AI 回答。 |
| reconcile | 固定目标、账号绑定和尝试证据 | 可复核提交记录／明确未提交证据／仍未知；只能读取，不能重发。 |

统一结果类型与稳定错误码，领域服务验证 URL、身份、全文完整性、字段来源和枚举；适配器无数据库写权限。页面 HTML 不执行脚本、不返回 Cookie／整个浏览器状态；必要字段／原文可持久化，不存无关页和上游原始错误。禁止将正文当提示词指令，模型只接收数据且引用须回到原文。

### 5.3 单进程生命周期与持久化防重入

复用后端生命周期，不新建独立调度平台。建议新增 Job-owned `collection_runs`：platform、purpose、scheduled_slot、strategy_fingerprint、触发 STARTUP/HOURLY/MANUAL、开始结束、status、计数、安全错误；slot 唯一，平台活跃 lease／fencing token。`job_observations` 引用 run；网络不持有长数据库事务。策略以 ProfilePreference 现有城市／分类和排除输入为基础，新增小型 versioned collection_settings JSON（正向关键词、平台、启用、预算），不把负向排除规则反转成搜索词。无正向范围就提示补充，不无界搜索。

Asia/Shanghai 判定“今天”。启动检查今天是否已有已持久化尝试，没有则排一次；失败算尝试，读取成功时间另算。运行期间每小时（已确认）创建时槽，时槽去重；睡眠／停机不补所有错过时槽，恢复只执行启动规则。只在能力通过且用户启用时运行，普通浏览 GET 不触发采集、解析、修订或外发。

领取 run 时短事务检查唯一槽、平台互斥和策略版本；心跳过期先确认旧 worker 停止再恢复读任务，新 fence 防止旧结果写回。每次详情短事务创建 STARTED，事务外读取，机会／posting 锁内完成入库与冲突处理；一个机会不同来源也在机会锁内处理。读操作可对明确暂时网络失败／429 按 Retry-After 在预算内至多重试一次，新尝试留下记录；结构错误、验证、登录失效不自动循环重试。建议详情超时15秒、整页操作2分钟、每周期最多20个详情／10分钟总预算；平台更严限制优先，参数外置可配置且不视作已确认指标。

策略映射建议：城市／正向关键词下推平台支持的搜索参数；公司性质、行业、外包等无法可靠筛选的在入库后按现有排除规则判定，未知标REVIEW。已保存更新只含该平台有稳定身份、非归档且策略允许／待核对的来源，轮转有界预算；申请已准备／进行中的跟进来源建议即使策略变化也继续只读检查并明确标注例外（此例外为建议，实施前核对）。手工无链接不进入平台更新，明确下架默认停止，用户可主动复查。策略切换显示增加／移除及跟进范围，不静默丢弃已保存内容。

Run 状态 QUEUED→RUNNING→SUCCEEDED/PARTIAL/FAILED/WAITING_USER/CANCELLED；分别统计发现、完整读取、采用、保护冲突、公司缺失、匹配完成／失败，不把部分结果包装全面成功。登录失效／验证码暂停该平台、人工登录后显式恢复；页面变化冻结能力等待验证；明确下架才标 UNAVAILABLE，失败不标下架，不改成功时间或当前 JD。

每个已接受的有效快照入库提交后触发固定输入匹配；相同 fingerprint 复用，重复内容仍记录观察但不重复生成相同报告。崩溃后从持久化已接受观察与匹配尝试恢复，不能靠内存队列保证不漏；匹配失败独立显示，不能回滚已保存 JD 或冒充采集失败。

### 5.4 模型外发与隐私

默认自动采集／自动匹配为本地处理，未配置模型仍可用。阶段一 AI 操作沿用逐次确认；自动批量模型调用若以后启用，必须另建有期限、可撤销的范围授权（用途、默认服务商／模型、具体字段、次数上限、保存说明），不从采集启用或单次 JD 确认推导长期授权。模型／字段范围变化需重确认，撤销阻止排队调用。

JD 解析只发必要原文，可能含招聘联系人须提示并在可保持摘录映射时脱敏；不要发 Cookie／会话。匹配及表达诊断若发档案／简历，默认剔除联系方式、头像和无关个人资料；记录确实外发字段与指纹，不记录密钥。平台搜索只发必要关键词／城市，不发候选人简历。模型返回内容不能直接写公司事实、授权或提交字段。外发失败不生成成功结论。

## 6. 确认后自动投递

### 6.1 固定对象与建议最小三表

全部归 Application，Resume 提供确定附件产物，automation 只执行。

| 表 | 核心字段／必要性 |
| --- | --- |
| submission_plans | application/opportunity/posting/snapshot/resume_version 明确 FK；目标平台 stable ID／URL、账号不透明绑定、适配器／表单／能力版本；实际字段、回答、问候语；附件定位、MIME、字节哈希、渲染／字体版本；策略输入及已确认例外；manifest schema／canonical hash；期限。内容不可变；authorized_at、revoked_at、consumed_at 授权元数据一次性受控更新。仅 ApplicationEvent 不能冻结文件字节。 |
| submission_tasks | plan_id 唯一；application_id、状态、lease/fence、取消请求、request_id、时间、错误、进度；同申请至多一个活动任务。求职状态不应承担排队／核实状态。 |
| submission_attempts | task_id、sequence 唯一；类型 DISPATCH/RECONCILE、开始结束、步骤／结果、side_effect_possible 标记、平台许可的幂等 token、回执类型／ID／安全摘录／哈希、账号目标绑定、request_id。终态与证据不可变；重试／核实各自新记录。只存任务最终状态会丢失外部风险证据。 |

具体 SQL 列名／约束实施时以 schema review 为准；不引入通用授权表、通用任务引擎或多租户账号表。plan 的快照必须属于 opportunity，resume 必须正式且不可变；准备阶段仍可修改 Application，但不得复写 plan 内容。附件通过 Resume 服务产出并保存不可变 bytes，服务器可回读验证哈希；现有浏览器打印预览不等于确定上传文件。渲染环境／分页／字体另做验收；只记录文件路径不足以证明上传内容。

### 6.2 确认、失效与事务

1. 用户明确选定 JD／正式简历→只读检查平台表单→冻结所有实际字段与附件。在线简历、平台已有默认字段也属于实际内容，无法查看／固定则该路径不可自动发送。预览不提前上传简历；上传本身已外发，必须包含在确认范围。
2. 返回不可变 plan，展示目标账号、收件岗位、附件实际预览、所有回答与可选字段；AI 候选用户审阅后才能纳入。生成后材料或目标变化必须新建 plan，不静默渲染替代版本。
3. confirm 请求提交 plan_id、manifest_hash、expected_application_version、单次确认 nonce 和明确 confirm；要求Application已READY_TO_APPLY，事务中重验材料、策略／例外、会话账号及有效能力。准备／就绪状态变更仍走原有事件入口，不把生成清单当作自动就绪。原子写授权、SUBMISSION_AUTHORIZED 事件及唯一 task，重复同一请求返回原 task，nonce 不跨清单复用。
4. 执行前重验实际字节、目标、账号、表单、能力及政策输入。不是每次检查 Application.version（任务自身审计会增长版本），而是比较材料／目标／策略指纹。当前采用 JD 已变化时暂停告知、重新核对所选历史材料，不悄悄替换或继续声称确认了最新内容；纯重复读取时间变化不使授权失效。
5. 材料、回答、目标、账号、表单、渲染 bytes、规则／例外依据变化或期限到期使 grant 失效，未派发任务原子取消；普通备注不影响授权。额外问题／验证码进入 WAITING_USER，补回答后必须新 plan 和新确认。建议授权短期有效（如30分钟），长时间排队过期要求重确认。
6. 发送边界之后拒绝修改绑定材料，直至结果核实；关闭／撤销申请只能请求停止并保留可能已发送的事实，不能改写历史。首次可靠成功在同一事务写 APPLIED 事件、锁固定材料、更新任务成功；平台成功而本地事务失败，由持久化发送标记进入 UNKNOWN 后核实，不重发。

本地单用户也要防非预期网页调用确认接口：可信 Origin／Host 校验、非简单请求、单次确认 nonce、清单 hash 与实际确认 UI 绑定；不能只收 confirm=true 就让适配器发送。未来暴露远程服务须另行认证／安全设计，不能用“个人使用”推导网络端点安全。

### 6.3 状态、并发与结果未知

Task：QUEUED→PREFLIGHT→DISPATCHING→SUCCEEDED；检查未满足→WAITING_USER；可证明无发送的错误→FAILED；发送可能已发生→UNKNOWN→VERIFYING→SUCCEEDED/UNKNOWN。发送边界前可 CANCELLED。WAITING_USER 修改材料回到新 plan 确认；失败重试也生成新 plan／明确确认，不重复消费旧授权。

平台／账号一次只执行一个表单任务；机会／账号的已有申请先读取并展示，已有 Application 重复申请沿用 confirm_repeat，平台禁止重复就降级。双击、并发确认、任务重复领取受唯一键、行锁和 fence 约束；用户打开两页不能绕过。执行器在上传／点击最终提交前先提交 side_effect_possible 标记及授权消费，后执行外部操作。标记后崩溃、断网或超时均 UNKNOWN，宁可待核实也不假定未发送。

租约过期不代表旧浏览器停止；数据库 fence 只能拒绝旧 worker 写回，不能撤销其已发网络请求。旧 worker 未确认终止及外部结果未核实前，替代 worker 只能查询，不能再提交。提供幂等 token 只在平台官方支持并已验证保证时使用，不自己造 token 宣称外部幂等。

取消在 side_effect_possible 前事务保证不派发；之后只记录取消请求并尽力停后续步骤，界面直说“可能已发送，正在核实”。不提供“撤回成功”的假回执。

### 6.4 成功证据与人工接管

| 情况 | 处理 |
| --- | --- |
| 成功回执 | 平台稳定申请／收件记录 ID、目标 stable ID、账号绑定和本次操作关联；或该平台经真实验证的等价确认凭据。结合派发前已申请基线排除旧记录，并关联固定 manifest。HTTP200、按钮点击、页面跳转和通用 toast 单独不够。 |
| 明确失败 | 平台可验证拒绝且确定未接收，记录安全原因与证据；不 APPLIED。上传后最终提交失败要记录材料已上传这一外发事实。 |
| 结果未知 | 保存全部已知步骤，只读查询申请历史／回执；没有记录可能是延迟，不能当未提交。建议限时核实后留 UNKNOWN 转人工，不自动“失败→重投”。 |
| 登录／验证码 | 暂停，用户在隔离浏览器自行完成，不采集密码／OTP、不绕验证码。恢复前确认账号与表单仍同一；变化就作废授权。 |
| 额外问题／附件缺失 | 保留任务、字段和进度，人工填写／修材料后新 plan；AI 不能自动回答开放问题或补虚构材料。 |
| 用户已在平台提交 | 独立「记录已在平台投递」填写实际目标、正式材料、时间和证据。USER_ATTESTED 与 PLATFORM_RECEIPT 分开标注；前者是用户陈述，不伪称平台验证。实际材料不同须先选／创建对应正式版本再事件化记录，不能锁一份随意简历；若未知实际材料则保留待核实笔记。 |
| UNKNOWN 后人工处理 | 人工记录实际已提交可终止自动重发并事件化锁材料；用户说“没投”本身不证明无外部效果，不据此自动重试。核实仍未知时保持未知，可由用户平台操作后如实记录。 |
| 不支持稳定自动化 | 下载固定文件、复制已审阅文本、打开原链接，用户自行提交，回 JobArk 记录历史；人工链路不需要等待自动化。 |

Application 求职状态仍 SAVED/PREPARING/READY_TO_APPLY/APPLIED 等；任务失败／等待不自动把申请标 REJECTED、APPLIED 或 CLOSED。SUBMISSION_* 审计事件可保持 before/to 状态相同，沿用顺序号；只在可靠成功／明确历史陈述时用既有 APPLIED 事件入口，禁止 worker 直接改 current_status。

### 6.5 会话与敏感材料

默认用户人工登录到隔离且短生命周期的浏览器上下文；会话只在运行内存／受控临时目录，退出销毁。账号绑定是非秘密不透明标识，不是密码或 Cookie。日志、JSON API、观察、Issue、仓库和错误均不保存密钥、Cookie、OTP、浏览器 Profile 或未经脱敏整页截屏。若未来确需持久化登录，单独 ADR 和用户选择，操作系统凭据库／加密目录置于仓库及普通 DB 外，不能复用 AI Key 表存 Cookie。

材料文件保存在受限应用数据目录，数据库只存不可变定位和校验；读取由专用 API 控制，不用公开静态路径；上传 URL 也不写日志。正式提交证据保留必要审计，不整份复制简历到每条事件；临时 HTML／浏览器状态任务结束清理。材料与证据删除要检查历史引用，归档不破坏已投递材料；确需物理删除另行确认目标与影响。诊断日志默认不含正文／联系方式，开发 SQL 也隐藏绑定参数。

## 7. API 与审计契约（建议，均非现有能力声明）

URL 前缀 `/api/v1`。所有成功 `{success:true,data:...,meta:{request_id}}`；失败 `{success:false,error:{code,message,details:[{field,reason}]},meta:{request_id}}`；分页参数 limit/cursor，meta.next_cursor。中文 summary／description 说明输入语义、外发／确认、副作用和主要错误，Pydantic 响应模型／前端类型同步；异步接受任务用202并返回任务 ID，不以200伪装失败。

| 接口 | 请求／响应核心字段和副作用 |
| --- | --- |
| POST /jobs/intake-preview | raw_jd、channel_name、url?、company_text?、engine LOCAL/AI、confirm_external?；返回 input_hash、原文、proposed_fields[{value,origin,quote}]、warnings。不保存职位，不访问平台；AI 确认缺失422。 |
| POST /jobs（扩展） | 现有请求兼容；company?、title?、raw_jd、渠道／链接、preview_hash?／来源字段；保存只接受经校验字段，返回已有机会／页面／快照聚合和 observation_id。操作幂等键同输入返回固定回执，不同输入409。 |
| PATCH /jobs/{id}/company（新增） | version、company_id? 或字段 patch 与 origin；关联和修订需明确动作、合法公司与源摘录；409 不覆盖。未知公司支持初次创建，不改 JD 内容版本。 |
| GET /jobs/{id}/observations | 获取／保存历史、来源、时间、结果／冲突，不返回会话／HTML；旧数据无观察明确历史未记录。 |
| POST /job-postings/{id}/adopt | observation_id、snapshot_id、expected_version、expected_current_fingerprint、allow_auto_update；采用候选与保护模式变更，422归属、409过期／冲突。 |
| POST /job-snapshots/{id}/parses；POST /matches（扩展） | 沿用现有本地／AI 外发确认；match 可选 parse_result_id，返回明确报告覆盖和版本。不把失败解析当匹配依据。 |
| GET/PUT /profile/preference（扩展） | collection_settings、version；复用现有单数路径及PUT整体替换规则，前端提交完整偏好以免清空旧字段，不新建第二策略根。读不启动扫描；启用须能力通过。 |
| POST /job-collection/runs；GET /job-collection/runs/{id} | 手工触发已启用 read scope／strategy version，202返回 run；读取阶段计数与安全错误。自动运行与手动相同幂等和互斥。 |
| POST /job-collection/runs/{id}/resume 或 /cancel | 修复验证／登录后恢复已允许读任务，不能自动开新能力；cancel 不改 JD。 |
| POST /applications/{id}/submission-plans | expected_version、posting_id、snapshot_id、resume_version_id、实际候选字段／附件格式；只读表单检查+冻结材料，201返回清单、hash、确认 nonce／期限、缺项。无自动能力可返回可人工操作的清单但不能授权自动执行。 |
| GET /submission-plans/{id}；GET /submission-plans/{id}/artifacts/{artifact_id} | 读取固定清单／附件 bytes，不触发重渲染、采集或提交；错误404／410明确文件缺失。 |
| POST /submission-plans/{id}/confirm | confirm=true、manifest_hash、expected_application_version、nonce；202固定 task_id，重复同确认回原任务，变更／失效409。 |
| POST /submission-plans/{id}/revoke | reason、version；撤销未消费授权，发送后返回取消请求／结果未知而非假称撤销外部动作。 |
| GET /submission-tasks/{id} | state、steps、attempts、safe_error、evidence_level、允许的人工动作。轮询有限间隔，可后续复用 SSE，但不强制新增系统。 |
| POST /submission-tasks/{id}/cancel；/reconcile | cancel 只请求停止；reconcile 仅新建只读核实尝试，202；不重投。 |
| POST /submission-tasks/{id}/manual-resolution | expected_version、actual_target／material IDs、user_confirmed、resolution、submitted_at?、evidence?；调用 Application 事件服务。未提交陈述不能自动解除未知；与现有历史 APPLIED 接口统一校验。 |

这些路径是开发契约建议，现有 API 精确字段／路由在各工作项中核对并兼容，不能直接把表格当作已部署 OpenAPI。Company、Task、Run 等读失败不得由前端吞成空集合。

| HTTP／错误码建议 | 场景和用户动作 |
| --- | --- |
| 422 INTAKE_INVALID／SOURCE_QUOTE_INVALID／MATERIALS_INCOMPLETE／CONFIRMATION_REQUIRED | 字段／原文／材料／确认缺失，保留内容就地修正。 |
| 404 RESOURCE_NOT_FOUND；410 ARTIFACT_UNAVAILABLE | 引用不在或材料缺失，不能拿其他历史替代。 |
| 409 VERSION_CONFLICT／IDENTITY_CONFLICT／CURRENT_CONTENT_CONFLICT | 数据变化或平台身份冲突，重新核对。 |
| 409 CAPABILITY_UNAVAILABLE／AUTHORIZATION_STALE／AUTHORIZATION_EXPIRED／SUBMISSION_IN_PROGRESS／DUPLICATE_APPLICATION／SUBMISSION_RESULT_UNKNOWN | 能力不支持、授权变化／过期、并发／重复或结果未知，按允许动作处理，禁盲重试。 |
| 409 LOGIN_REQUIRED／HUMAN_VERIFICATION_REQUIRED／FORM_CHANGED | 正常依赖阻断转人工，不把平台登录失效混成 JobArk API401。 |
| 429 COLLECTION_RATE_LIMITED；502 PLATFORM_CONTENT_INVALID；504 PLATFORM_TIMEOUT | 预算、结构变化或读取超时；发送后的超时返回任务 UNKNOWN，而非诱导客户端重发的普通504。 |
| 401 UNAUTHENTICATED；403 ORIGIN_NOT_ALLOWED；500 INTERNAL_ERROR | 若引入服务认证沿用统一处理；禁止泄漏堆栈、Cookie或平台原始报错。 |

同步请求错误与异步任务 safe_error 区分；已有错误码优先复用，新码集中注册，不散落字符串。审计最少记录 request_id、操作类型、用户／调度触发、输入 fingerprint、关联实体、版本／能力、时间、结果／原因、授权与撤销、外部发送边界和证据等级。日志不作唯一事实，关键审计落领域数据库；引用报告／简历／JD ID 而非重复正文。

## 8. 分阶段交付、验收与停止条件

| 阶段 | 前置依赖／最小独立范围 | 正常与失败验收 | 扩展／停止条件 |
| --- | --- | --- | --- |
| 一 | 现有手工／当前 JD／解析／申请材料；先 JD-only 与来源，再报告维度。仅复制、核对、保存、明确覆盖的评估、手工材料与历史记录，不依赖模型或平台。 | 只有 JD 可保存评估；无链接／公司缺失未知展示；常用／自定义渠道；候选保留原文、失败留草稿；保存和分析分离；硬条件／表达／未知分开；A→B→A、多来源并列、历史不写指针；解析／读取／422／409安全失败。 | 本地链路可信即可独立交付；未知维度标未知，AI／公司缺失均退回手工，不以模型失败阻断。 |
| 二 | 阶段一、单平台获准只读能力验证、来源观察／保护、偏好策略、持久化run与固定输入分析。先用户指定链接只读试点，READ_SEARCH通过后启用策略、启动检查与每小时；无外部提交。 | 有效结果自动保存与匹配；重复内容留观察／复用报告；人工保护跨来源有效；公司提取失败不丢JD；登录／验证码待人工；下架和失败区分；并发／重启／时槽去重、部分成功真实计数。 | 许可不明、正文不完整、频率不允许或连续页面变化就停能力；不扩大抓取。只读允许范围不足降级链接更新或复制内容。 |
| 三 | 阶段一材料／ApplicationEvent、Resume确定附件、阶段二平台验证结果及**独立**SUBMIT/READ_FORM/READ_RECEIPT验证；采集许可不够。最小为单平台单条明确确认、可核实回执和人工接管，不做批量无人值守。 | 未确认零发送；字节／目标／字段变化失效；双击仅一个任务；排队取消不发送；发送后失联未知不重投；可靠回执事件化APPLIED锁材料；额外问题／验证码暂停；人工历史材料如实记录、证据等级明确。 | 无完整预览、稳定表单或可靠回执就保持人工。真实提交试点须另外确认具体目标和材料；设计授权不够。 |

### 8.1 验证证据分层

- 自动测试：阶段一请求旧契约／空关联／摘录校验／公司来源修订、不可变历史、原文完整、失败保留及报告维度；阶段二随机 schema 并发、重复槽、lease／fence、崩溃恢复、自动候选保护、A→B→A、下架与失败、匹配复用与失败恢复，mock 每个平台错误；阶段三模拟上传前后断网／DB失败／旧worker继续执行、授权变更与到期、重复确认／申请、回执关联旧记录、UNKNOWN禁止重发、取消竞态、人工核实／材料锁以及日志不含秘密。所有 DB 用例沿用 UUID schema 隔离，不碰业务 schema。
- 浏览器验收：本地真实页面桌面与窄窗口；复制／补充／原文折行、加载／失败／冲突草稿、当前历史选取、报告引用定位、材料文件预览／分页／下载哈希、键盘确认／取消、任务进度与人工接管；模拟平台验收只证明本地交互，不证明真实平台。
- 真实平台验证：许可与能力范围、会话／验证码退路、实际搜索和完整JD／公司信息、页面变化、真实频率和运行环境、线上简历／表单内容可固定、真实附件格式／字节接收、可靠回执及重复查询、结果未知核实。必须单列样本和证据；未经另行授权不向真实招聘方发送。

每个工作项交付时执行受影响后端／前端测试、lint、类型检查、生产构建及真实浏览器检查；只改文档的本次不执行这些业务验证。平台验证失败不影响完成本地阶段，不用“测试通过”替代平台准入。

## 9. 实施建议与用户决定

推荐阶段二默认自动生成 Profile Match，简历评估在用户明确选择正式版本后生成；避免自动把上次岗位简历绑定到新岗位。只有希望自动批量生成 Resume Match 时才需要产品选择：固定一个正式版本，还是每次人工选择；推荐人工选择。具体表结构／接口命名／预算属于可 review 的实施建议，无需用户逐项决定技术细节。

尚无经核实的平台获准方式和可靠回执，这是准入依赖而不是让用户猜测平台能力的问题。确认第一平台或本设计不授权真实发送。设计工作不创建业务表、迁移数据、开启采集、外发简历或推送代码。

## 2026-10-07 分析范围修订

本轮以 [JD 分析正式需求](requirements/jd-analysis.md) 和 ADR 0007 为准。允许新 schema 的可解释 10 分参考区间；旧 overall_score 保持 null，不回填。未知不计零，硬限制优先，禁止录用概率、无依据总分和自动淘汰。JobOpportunity.company_id/title 可空，Company.name 仍必填，不建占位公司。ProfilePreference 增加有版本的目标方向、显式硬限制口径和优先名单；旧偏好不升级为硬限制。MatchResult 增加可空成功解析引用，报告 JSON 冻结必要策略、条件与算法/模型版本并记录内容指纹。公司公开报告及来源归 Job，独立不可变，不改变确认分类或能力分。外发确认和事务边界沿用既有约束；自动采集、调度、外部投递不在本轮实现范围。本文是后续范围决策，不是实现或真实运行验收声明。
