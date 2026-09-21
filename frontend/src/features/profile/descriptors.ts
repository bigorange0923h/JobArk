/**
 * 六类事实的界面描述符。
 *
 * 这里是"表单字段、表格列、写操作"的单一来源：面板组件只按描述符渲染，页面只按描述符接线，
 * 因此新增一类事实或调整某类字段只需要动这一个文件。
 *
 * 未暴露 `sort_order`：后端已为事实表存了该字段，但档案聚合返回时并不按它排序，界面上会表现为
 * "填了顺序却没有效果"。等后端按它排序（或在聚合里显式排序）之后再暴露，避免给出无效操作。
 */

import {
  educationsApi,
  evidencesApi,
  experiencesApi,
  languagesApi,
  projectsApi,
  skillsApi,
  type ClaimStatus,
  type Education,
  type EducationInput,
  type Evidence,
  type EvidenceInput,
  type EvidenceSourceType,
  type Experience,
  type ExperienceInput,
  type Language,
  type LanguageInput,
  type Project,
  type ProjectInput,
  type Skill,
  type SkillInput,
  type SkillProficiency,
  type VerificationStatus,
} from '@/shared/api/profile'

import type { FactDescriptor, FieldOption } from './types'

// 值 → 中文标签的唯一来源：展示与下拉选项都从这里派生，避免出现"表格显示已验证、下拉里写成
// 已确认"这类两处各写一遍造成的漂移。
const CLAIM_STATUS_LABELS: Record<ClaimStatus, string> = {
  VERIFIED: '已验证',
  UNVERIFIED: '未验证',
  UNCERTAIN: '不确定',
}

const VERIFICATION_STATUS_LABELS: Record<VerificationStatus, string> = {
  VERIFIED: '已验证',
  UNVERIFIED: '未验证',
  UNCERTAIN: '不确定',
}

const EVIDENCE_SOURCE_TYPE_LABELS: Record<EvidenceSourceType, string> = {
  MANUAL_DECLARATION: '本人陈述',
  RESUME_DOCUMENT: '历史简历',
  WORK_PROOF: '工作产出/任职证明',
  PROJECT_LINK: '项目链接',
  CERTIFICATE: '证书',
  OTHER: '其他',
}

const SKILL_PROFICIENCY_LABELS: Record<SkillProficiency, string> = {
  BASIC: '入门',
  INTERMEDIATE: '熟练',
  ADVANCED: '精通',
  EXPERT: '专家',
}

const CLAIM_STATUS_OPTIONS: FieldOption[] = toOptions(CLAIM_STATUS_LABELS)
const VERIFICATION_STATUS_OPTIONS: FieldOption[] = toOptions(VERIFICATION_STATUS_LABELS)
const EVIDENCE_SOURCE_TYPE_OPTIONS: FieldOption[] = toOptions(EVIDENCE_SOURCE_TYPE_LABELS)
const SKILL_PROFICIENCY_OPTIONS: FieldOption[] = toOptions(SKILL_PROFICIENCY_LABELS)

/** 断言偏好字段的枚举选项由偏好组件自行定义，见 `PreferencePanel.vue`。 */
export const REMOTE_PREFERENCE_LABELS = {
  ANY: '不限',
  ONSITE: '坐班',
  HYBRID: '混合',
  REMOTE: '远程',
} as const

function toOptions(labels: Record<string, string>): FieldOption[] {
  return Object.entries(labels).map(([value, label]) => ({ value, label }))
}

/**
 * 可被新事实引用的证据选项。
 *
 * 排除已归档的证据：后端对引用已归档证据的写入返回 422，若在这里仍然列出，用户会选中一个
 * 必然失败的值。历史事实仍引用着已归档证据，因此展示时不能过滤，只有新增引用时才排除。
 */
function usableEvidenceOptions(evidences: Evidence[]): FieldOption[] {
  return evidences
    .filter((item) => item.archived_at === null)
    .map((item) => ({ value: item.id, label: item.title }))
}

/** 把证据 id 显示为证据标题，供表格列使用。 */
function evidenceTitle(item: { source_evidence_id: string | null }, evidences: Evidence[]): string {
  if (item.source_evidence_id === null) {
    return '—'
  }
  const found = evidences.find((candidate) => candidate.id === item.source_evidence_id)
  return found === undefined ? '(证据已不可用)' : found.title
}

/** 证据面板。 */
export function evidenceDescriptor(): FactDescriptor<Evidence, EvidenceInput> {
  return {
    key: 'evidences',
    title: '证据',
    description: '真实信息来源。技能、经历等主张通过引用证据来说明依据；界面的"归档"不删除记录，历史引用仍然成立。',
    removeLabel: '归档',
    rowLabel: (item) => item.title,
    operations: evidencesApi,
    fields: [
      { name: 'title', label: '标题', kind: 'text', required: true, maxLength: 200 },
      {
        name: 'source_type',
        label: '来源类别',
        kind: 'select',
        required: true,
        options: EVIDENCE_SOURCE_TYPE_OPTIONS,
      },
      {
        name: 'verification_status',
        label: '可核验程度',
        kind: 'select',
        options: VERIFICATION_STATUS_OPTIONS,
        help: '没有客观凭据时请保持"未验证"，不要为了好看而标成已验证。',
      },
      { name: 'source_url', label: '外部链接', kind: 'text', maxLength: 2048, placeholder: 'https://…' },
      {
        name: 'source_hash',
        label: '来源哈希',
        kind: 'text',
        maxLength: 128,
        help: '用于识别同一份证据的重复导入；手工录入可留空。',
      },
      { name: 'content', label: '内容或说明', kind: 'textarea' },
    ],
    columns: [
      { name: 'title', label: '标题' },
      { name: 'source_type', label: '来源', format: (item) => EVIDENCE_SOURCE_TYPE_LABELS[item.source_type] },
      {
        name: 'verification_status',
        label: '可核验程度',
        format: (item) => VERIFICATION_STATUS_LABELS[item.verification_status],
      },
      { name: 'archived_at', label: '状态', format: (item) => (item.archived_at === null ? '生效中' : '已归档') },
    ],
  }
}

/** 技能面板。 */
export function skillDescriptor(evidences: Evidence[]): FactDescriptor<Skill, SkillInput> {
  return {
    key: 'skills',
    title: '技能',
    description: '同一档案内技能名不可重复；标记为"已验证"时必须同时关联证据，否则后端拒绝写入。',
    rowLabel: (item) => item.name,
    operations: skillsApi,
    fields: [
      { name: 'name', label: '技能名称', kind: 'text', required: true, maxLength: 100 },
      { name: 'category', label: '分类', kind: 'text', maxLength: 64, placeholder: '语言 / 框架 / 工具' },
      { name: 'proficiency', label: '熟练度', kind: 'select', options: SKILL_PROFICIENCY_OPTIONS },
      {
        name: 'years_of_experience',
        label: '使用年限',
        kind: 'number',
        help: '可填小数，例如 3.5。',
      },
      {
        name: 'source_evidence_id',
        label: '来源证据',
        kind: 'evidence',
        options: usableEvidenceOptions(evidences),
        help: '选择后即可把"验证状态"标为已验证。',
      },
      {
        name: 'claim_status',
        label: '验证状态',
        kind: 'select',
        options: CLAIM_STATUS_OPTIONS,
        help: '标为已验证前，请先在上方选择来源证据。',
      },
    ],
    columns: [
      { name: 'name', label: '技能' },
      { name: 'category', label: '分类' },
      { name: 'proficiency', label: '熟练度', format: (item) => formatProficiency(item.proficiency) },
      { name: 'claim_status', label: '验证状态', format: (item) => CLAIM_STATUS_LABELS[item.claim_status] },
      { name: 'source_evidence_id', label: '来源证据', format: (item) => evidenceTitle(item, evidences) },
    ],
  }
}

/** 工作经历面板。 */
export function experienceDescriptor(evidences: Evidence[]): FactDescriptor<Experience, ExperienceInput> {
  return {
    key: 'experiences',
    title: '工作经历',
    description: '结束日期留空表示当前仍在职；结束日期早于开始日期会被拒绝。',
    rowLabel: (item) => `${item.company} · ${item.title}`,
    operations: experiencesApi,
    fields: [
      { name: 'company', label: '公司', kind: 'text', required: true, maxLength: 200 },
      { name: 'title', label: '职位', kind: 'text', required: true, maxLength: 200 },
      { name: 'location', label: '地点', kind: 'text', maxLength: 100 },
      { name: 'start_date', label: '开始日期', kind: 'date', required: true },
      { name: 'end_date', label: '结束日期', kind: 'date', help: '留空表示当前仍在职。' },
      { name: 'responsibilities', label: '职责', kind: 'textarea' },
      {
        name: 'achievements',
        label: '成果',
        kind: 'textarea',
        help: '尽量写可量化的结果：简历生成与匹配都以这里的内容为依据。',
      },
      { name: 'source_evidence_id', label: '来源证据', kind: 'evidence', options: usableEvidenceOptions(evidences) },
    ],
    columns: [
      { name: 'company', label: '公司' },
      { name: 'title', label: '职位' },
      { name: 'start_date', label: '开始' },
      { name: 'end_date', label: '结束', format: (item) => item.end_date ?? '至今' },
      { name: 'source_evidence_id', label: '来源证据', format: (item) => evidenceTitle(item, evidences) },
    ],
  }
}

/** 项目面板。 */
export function projectDescriptor(evidences: Evidence[]): FactDescriptor<Project, ProjectInput> {
  return {
    key: 'projects',
    title: '项目经历',
    description: '工作项目与个人项目都可以记录，不强制绑定到某段工作经历。',
    rowLabel: (item) => item.name,
    operations: projectsApi,
    fields: [
      { name: 'name', label: '项目名称', kind: 'text', required: true, maxLength: 200 },
      { name: 'role', label: '本人角色', kind: 'text', maxLength: 100 },
      { name: 'description', label: '项目说明', kind: 'textarea' },
      { name: 'tech_stack', label: '技术栈', kind: 'tags', help: '输入后回车添加，可填多个。' },
      { name: 'url', label: '项目链接', kind: 'text', maxLength: 2048, placeholder: 'https://…' },
      { name: 'start_date', label: '开始日期', kind: 'date' },
      { name: 'end_date', label: '结束日期', kind: 'date' },
      { name: 'source_evidence_id', label: '来源证据', kind: 'evidence', options: usableEvidenceOptions(evidences) },
    ],
    columns: [
      { name: 'name', label: '项目' },
      { name: 'role', label: '角色' },
      { name: 'tech_stack', label: '技术栈', format: (item) => (item.tech_stack.length === 0 ? '—' : item.tech_stack.join('、')) },
    ],
  }
}

/** 教育经历面板。 */
export function educationDescriptor(evidences: Evidence[]): FactDescriptor<Education, EducationInput> {
  return {
    key: 'educations',
    title: '教育经历',
    description: '学历信息以本人录入或可信证据为准，系统不会替你推断。',
    rowLabel: (item) => item.school,
    operations: educationsApi,
    fields: [
      { name: 'school', label: '学校', kind: 'text', required: true, maxLength: 200 },
      { name: 'major', label: '专业', kind: 'text', maxLength: 200 },
      { name: 'degree', label: '学历/学位', kind: 'text', maxLength: 64, placeholder: '本科 / 硕士' },
      { name: 'start_date', label: '开始日期', kind: 'date' },
      { name: 'end_date', label: '结束日期', kind: 'date' },
      { name: 'source_evidence_id', label: '来源证据', kind: 'evidence', options: usableEvidenceOptions(evidences) },
    ],
    columns: [
      { name: 'school', label: '学校' },
      { name: 'major', label: '专业' },
      { name: 'degree', label: '学历/学位' },
      { name: 'source_evidence_id', label: '来源证据', format: (item) => evidenceTitle(item, evidences) },
    ],
  }
}

/** 语言能力面板。 */
export function languageDescriptor(evidences: Evidence[]): FactDescriptor<Language, LanguageInput> {
  return {
    key: 'languages',
    title: '语言能力',
    description: '语言水平属于本人陈述；需要作为已验证事实时，请先录入证书类证据再关联。',
    rowLabel: (item) => item.language,
    operations: languagesApi,
    fields: [
      { name: 'language', label: '语言', kind: 'text', required: true, maxLength: 64 },
      { name: 'level', label: '水平', kind: 'text', maxLength: 64, placeholder: 'CET-6 / 雅思 7.0' },
      { name: 'note', label: '说明', kind: 'textarea' },
      { name: 'source_evidence_id', label: '来源证据', kind: 'evidence', options: usableEvidenceOptions(evidences) },
    ],
    columns: [
      { name: 'language', label: '语言' },
      { name: 'level', label: '水平' },
      { name: 'note', label: '说明' },
      { name: 'source_evidence_id', label: '来源证据', format: (item) => evidenceTitle(item, evidences) },
    ],
  }
}

function formatProficiency(value: SkillProficiency | null): string {
  return value === null ? '—' : SKILL_PROFICIENCY_LABELS[value]
}
