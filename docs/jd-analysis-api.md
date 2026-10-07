# JD 条件分析接口与兼容边界

`POST /api/v1/jobs/manual` 允许仅 raw_jd：company/title 缺失保存 NULL，Company.name 仍不可空。JobOpportunity 的 work_terms 只接受用户明确确认的 remote_mode 和 salary；薪资最小/最大、币种、MONTH/YEAR、GROSS/NET 不从原文推算。PATCH 按既有乐观锁保存；空白原文、错误口径或倒置区间422，缺资源404，版本冲突409。

ProfilePreference 新增 target_roles、hard_limits、priority_rules；旧记录默认空目标、无硬限制、无优先规则。开启硬限制须同时提供对应值。优先名单复用名称/行业/关键词规则，与排除策略分别计算，不加分、不抵消排除。不实现仅白名单模式。

`POST /api/v1/matches` 新路径提交 job_snapshot_id、profile_revision_id、parse_result_id，可选同修订 resume_version_id；engine 为 LOCAL/AI。引用不存在404，失败解析/跨快照/跨修订422。AI 还需 confirm_external=true、expected_service、expected_model，目标须与本次实际默认模型一致，否则409。确定排除或硬冲突停止模型调用，仍可生成本地解释。没有 parse_result_id 时保留旧本地字面报告路径，不允许 AI。

报告 schema_version=jd-analysis-v2，overall_score 仍 null，reference_score 包含 lower/upper/coverage/single_score、条件权重、依据与建议。指纹覆盖实际快照原文、解析内容、资料事实/来源证据、可选简历、策略、版本及模型信息。同输入顺序重试复用既有报告，持久化用 PostgreSQL 事务锁防止并发重复；并发外部请求可能各自消耗模型额度，本轮没有网络任务去重平台。旧报告不回填或改写；读取 is_stale 对新报告比较当前 JD、相关策略和资料，旧报告为 null。

本地结果只把技能名称对应作为有限背景线索，职责/准入缺乏证据保持未知。模型引用必须属于冻结修订且摘录可定位，引用校验不代表事实已经独立核实。LOCAL 解析版本更新为 literal-lines-v2，旧解析仍可显式选用。

公司报告接口独立于 MatchResult，详见 [公司搜索协议](company-research-api.md)。本轮不自动把公司风险并入匹配建议，也不计入能力适配分；用户从独立风险栏目核对。自动招聘提交不在接口行为内。
