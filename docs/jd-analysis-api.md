# JD 条件分析接口与兼容边界

`POST /api/v1/jobs/manual` 允许仅 raw_jd：company/title 缺失保存 NULL，Company.name 仍不可空。JobOpportunity 的 work_terms 只接受用户明确确认的 remote_mode 和 salary；薪资最小/最大、币种、MONTH/YEAR、GROSS/NET 不从原文推算。PATCH 按既有乐观锁保存；空白原文、错误口径或倒置区间422，缺资源404，版本冲突409。

ProfilePreference 新增 target_roles、hard_limits、priority_rules；旧记录默认空目标、无硬限制、无优先规则。开启硬限制须同时提供对应值。优先名单复用名称/行业/关键词规则，与排除策略分别计算，不加分、不抵消排除。不实现仅白名单模式。

`POST /api/v1/matches` 新路径提交 job_snapshot_id、profile_revision_id、parse_result_id，可选同修订 resume_version_id；engine 为 LOCAL/AI。引用不存在404，失败解析/跨快照/跨修订422。AI 还需 confirm_external=true、expected_service、expected_model，目标须与本次实际默认模型一致，否则409。确定排除或硬冲突停止模型调用，仍可生成本地解释。没有 parse_result_id 时保留旧本地字面报告路径，不允许 AI。

报告 schema_version=jd-analysis-v2，overall_score 仍 null，reference_score 包含 lower/upper/coverage/single_score、条件权重、依据与建议。指纹覆盖实际快照原文、解析内容、资料事实/来源证据、可选简历、策略、版本及模型信息。同输入顺序重试复用既有报告，持久化用 PostgreSQL 事务锁防止并发重复；并发外部请求可能各自消耗模型额度，本轮没有网络任务去重平台。旧报告不回填或改写；读取 is_stale 对新报告比较当前 JD、相关策略和资料，旧报告为 null。

本地结果只把技能名称对应作为有限背景线索，职责/准入缺乏证据保持未知。模型引用必须属于冻结修订且摘录可定位，引用校验不代表事实已经独立核实。LOCAL 解析版本更新为 literal-conditions-v3，旧解析仍可显式选用。

公司报告接口独立于 MatchResult，详见 [公司搜索协议](company-research-api.md)。本轮不自动把公司风险并入匹配建议，也不计入能力适配分；用户从独立风险栏目核对。自动招聘提交不在接口行为内。

## 条件与策略调整（0017）

教育 POST/PATCH 新增可空 degree_level/study_mode，非法枚举422；旧 degree 不回填，资料修订保留新字段。导入确认接受本人填写的结构化字段；模型预览不猜测，追加 FIELD_NOT_IN_QUOTE 提示并清空模型结构化值，保留原学历描述。

偏好 PUT/GET 新增 role_keywords 和 acceptable_salary_min。独立底线高于期望下限返回422，工作方式 ANY 不能启用 remote 硬限制。salary_basis 继续通过 hard_limits 保存，也用于软薪资比较。达到期望下限锚点1，达到独立底线但低于期望0.5，没有独立底线且明确低于期望为软偏好0；跨底线、跨期望边界或口径缺失未知。硬薪资底线作为单独条件，仅在 salary 开启时加入，其与期望比较共享既有薪资维度权重，不扩大全局权重。高于期望上界不扣分，报告保留期望区间说明。

方向标题命中0.75、正文方向命中0.5、已声明方向且补充关键词命中0.25，无确定线索未知；仍是保守字面线索，不是完整语义适配。原关键词 target_roles 保留，不自动迁移到新字段。

本地解析 literal-conditions-v3 跳过标题，拆安全并列分句，原文偏移可核对；OR 整体保持未知，不把全部选项当必需。明确无准入才 NOT_APPLICABLE；旧/新解析未识别时 UNKNOWN。报告 scoring six-dimensions-v2/prompt condition-anchors-v2，追加逐项原文位置/关系、fact_quote、source_support（EXCERPT_SUPPORTED/SOURCE_ATTACHED/SELF_DECLARED）和 data_warnings，旧字段兼容。摘录支持只针对该片段，不宣称能力已独立核验。
