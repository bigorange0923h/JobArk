/**
 * Profile 领域的接口调用与类型。
 *
 * 类型是后端 schema 的**手工镜像**（对应 `backend/app/modules/profile/schemas.py`）：只写界面实际
 * 用到的字段，不追求逐字复制。手工维护的代价是后端改字段时前端不会自动报错，因此每个类型都标注了
 * 来源；后端契约变更时必须回来核对这里。
 *
 * 本模块只声明"路径 + 方法 + 类型"，不做业务判断：例如"标记为已验证时必须挂证据""被修订引用的
 * 事实不可删除"都由后端裁决，前端只负责把后端返回的错误码与字段级原因呈现出来。
 */

import { requestV1 } from './client'

// --------------------------------------------------------------------------------------------
// 枚举：取值必须与 backend/app/modules/profile/enums.py 一致，否则会在服务端被 CHECK 约束拒绝
// --------------------------------------------------------------------------------------------

/** 主张的验证状态。 */
export type ClaimStatus = 'VERIFIED' | 'UNVERIFIED' | 'UNCERTAIN'

/** 证据来源类别。 */
export type EvidenceSourceType =
  | 'MANUAL_DECLARATION'
  | 'RESUME_DOCUMENT'
  | 'WORK_PROOF'
  | 'PROJECT_LINK'
  | 'CERTIFICATE'
  | 'OTHER'

/** 证据自身的可核验程度。 */
export type VerificationStatus = 'VERIFIED' | 'UNVERIFIED' | 'UNCERTAIN'

/** 技能熟练度，仅用于展示与排序，不构成事实主张。 */
export type SkillProficiency = 'BASIC' | 'INTERMEDIATE' | 'ADVANCED' | 'EXPERT'

/** 远程工作偏好。 */
export type RemotePreference = 'ANY' | 'ONSITE' | 'HYBRID' | 'REMOTE'

// --------------------------------------------------------------------------------------------
// 响应类型
// --------------------------------------------------------------------------------------------

/** 可编辑实体的公共字段。 */
export interface EditableResource {
  id: string
  created_at: string
  updated_at: string
  /** 乐观锁版本号：局部更新必须原样回传，不一致时后端返回 409。 */
  version: number
}

/** 公开链接。 */
export interface ProfileLink {
  label: string
  url: string
}

/** 真实信息来源。 */
export interface Evidence extends EditableResource {
  source_type: EvidenceSourceType
  title: string
  content: string | null
  source_url: string | null
  source_hash: string | null
  verification_status: VerificationStatus
  /** 非空表示已归档；归档证据不可再被新事实引用。 */
  archived_at: string | null
}

/** 技能事实。 */
export interface Skill extends EditableResource {
  name: string
  name_normalized: string
  category: string | null
  proficiency: SkillProficiency | null
  /** 后端为 Decimal，JSON 中序列化为字符串（如 `"3.5"`）；提交时字符串同样会被解析。 */
  years_of_experience: string | null
  source_evidence_id: string | null
  claim_status: ClaimStatus
}

/** 工作经历。 */
export interface Experience extends EditableResource {
  company: string
  title: string
  location: string | null
  start_date: string
  end_date: string | null
  responsibilities: string | null
  achievements: string | null
  source_evidence_id: string | null
}

/** 项目经历。 */
export interface Project extends EditableResource {
  name: string
  role: string | null
  description: string | null
  tech_stack: string[]
  url: string | null
  start_date: string | null
  end_date: string | null
  source_evidence_id: string | null
}

/** 教育经历。 */
export interface Education extends EditableResource {
  school: string
  major: string | null
  degree: string | null
  start_date: string | null
  end_date: string | null
  source_evidence_id: string | null
}

/** 语言能力。 */
export interface Language extends EditableResource {
  language: string
  level: string | null
  note: string | null
  source_evidence_id: string | null
}

/** 求职偏好；属于可变规则，不是履历事实。 */
export interface Preference extends EditableResource {
  target_locations: string[]
  job_types: string[]
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  remote_preference: RemotePreference | null
  exclusions: string[]
}

/** 不可变的资料修订快照。 */
export interface Revision {
  id: string
  profile_id: string
  revision_no: number
  snapshot_json: Record<string, unknown>
  reason: string
  created_at: string
}

/** 个人档案聚合；单用户小数据量下一次返回全部子项。 */
export interface Profile extends EditableResource {
  singleton_key: string
  full_name: string
  headline: string | null
  summary: string | null
  email: string | null
  phone: string | null
  city: string | null
  links: ProfileLink[]
  evidences: Evidence[]
  skills: Skill[]
  experiences: Experience[]
  projects: Project[]
  educations: Education[]
  languages: Language[]
  preference: Preference | null
}

// --------------------------------------------------------------------------------------------
// 请求体类型
// --------------------------------------------------------------------------------------------

/** 档案根信息的创建请求体。 */
export interface ProfileCreateInput {
  full_name: string
  headline?: string | null
  summary?: string | null
  email?: string | null
  phone?: string | null
  city?: string | null
  links?: ProfileLink[]
}

/** 档案根信息的局部更新请求体。 */
export interface ProfileBasicsInput {
  version: number
  full_name?: string
  headline?: string | null
  summary?: string | null
  email?: string | null
  phone?: string | null
  city?: string | null
  links?: ProfileLink[]
}

/** 证据的写入请求体（创建与更新共用；更新时由接口层补上 `version`）。 */
export interface EvidenceInput {
  source_type: EvidenceSourceType
  title: string
  content?: string | null
  source_url?: string | null
  source_hash?: string | null
  verification_status?: VerificationStatus
}

/** 技能的写入请求体。 */
export interface SkillInput {
  name: string
  category?: string | null
  proficiency?: SkillProficiency | null
  years_of_experience?: string | null
  source_evidence_id?: string | null
  claim_status?: ClaimStatus
}

/** 工作经历的写入请求体。 */
export interface ExperienceInput {
  company: string
  title: string
  location?: string | null
  start_date: string
  end_date?: string | null
  responsibilities?: string | null
  achievements?: string | null
  source_evidence_id?: string | null
}

/** 项目的写入请求体。 */
export interface ProjectInput {
  name: string
  role?: string | null
  description?: string | null
  tech_stack?: string[]
  url?: string | null
  start_date?: string | null
  end_date?: string | null
  source_evidence_id?: string | null
}

/** 教育经历的写入请求体。 */
export interface EducationInput {
  school: string
  major?: string | null
  degree?: string | null
  start_date?: string | null
  end_date?: string | null
  source_evidence_id?: string | null
}

/** 语言能力的写入请求体。 */
export interface LanguageInput {
  language: string
  level?: string | null
  note?: string | null
  source_evidence_id?: string | null
}

/** 求职偏好的整体替换请求体。 */
export interface PreferenceInput {
  target_locations?: string[]
  job_types?: string[]
  salary_min?: number | null
  salary_max?: number | null
  salary_currency?: string | null
  remote_preference?: RemotePreference | null
  exclusions?: string[]
  /** 偏好已存在时必须提供；首次创建时省略。 */
  version?: number
}

// --------------------------------------------------------------------------------------------
// 通用事实接口
// --------------------------------------------------------------------------------------------

/**
 * 一类事实的写操作集合。
 *
 * 六类事实（证据、技能、经历、项目、教育、语言）的接口形状完全一致，差异只在路径与字段，
 * 因此在这里统一构造：界面层只依赖这个接口，不需要为每类事实重复实现一遍调用逻辑。
 *
 * 读取不在此处：页面通过 `GET /profile` 一次拿到全部子项，不需要逐类列表接口。
 */
export interface FactApi<TRead, TPayload> {
  create: (payload: TPayload) => Promise<TRead>
  update: (id: string, payload: TPayload & { version: number }) => Promise<TRead>
  remove: (id: string) => Promise<{ id: string }>
}

/** 构造一类事实的写操作集合。 */
export function createFactApi<TRead, TPayload>(path: string): FactApi<TRead, TPayload> {
  return {
    create: (payload) => requestV1<TRead>(path, { init: jsonInit('POST', payload) }),
    update: (id, payload) => requestV1<TRead>(`${path}/${id}`, { init: jsonInit('PATCH', payload) }),
    // 证据的 DELETE 在后端实现为归档（写 archived_at），方法名保持 remove 以免界面层假设是物理删除。
    remove: (id) => requestV1<{ id: string }>(`${path}/${id}`, { init: { method: 'DELETE' } }),
  }
}

/** 事实接口路径，与后端路由一一对应。 */
export const evidencesApi = createFactApi<Evidence, EvidenceInput>('/profile/evidences')
export const skillsApi = createFactApi<Skill, SkillInput>('/profile/skills')
export const experiencesApi = createFactApi<Experience, ExperienceInput>('/profile/experiences')
export const projectsApi = createFactApi<Project, ProjectInput>('/profile/projects')
export const educationsApi = createFactApi<Education, EducationInput>('/profile/educations')
export const languagesApi = createFactApi<Language, LanguageInput>('/profile/languages')

// --------------------------------------------------------------------------------------------
// 档案根、偏好与修订
// --------------------------------------------------------------------------------------------

/**
 * 读取个人档案聚合。
 *
 * 异常:
 *    ApiError：档案尚未创建时 `code` 为 `RESOURCE_NOT_FOUND`，调用方据此展示创建引导。
 */
export function fetchProfile(): Promise<Profile> {
  return requestV1<Profile>('/profile')
}

/** 创建个人档案。V1 只允许一份，重复创建返回 409。 */
export function createProfile(payload: ProfileCreateInput): Promise<Profile> {
  return requestV1<Profile>('/profile', { init: jsonInit('POST', payload) })
}

/** 局部更新档案根信息；必须提交当前 `version`。 */
export function saveProfileBasics(payload: ProfileBasicsInput): Promise<Profile> {
  return requestV1<Profile>('/profile', { init: jsonInit('PATCH', payload) })
}

/**
 * 创建或整体替换求职偏好：未提交的字段按清空处理。
 *
 * 说明:
 *    刻意不提供"单独读取偏好"的封装：偏好已经包含在档案聚合里，再提供一个读取入口会产生
 *    两处可能不一致的来源（聚合里的与单独请求的），而界面只需要一份。
 */
export function savePreference(payload: PreferenceInput): Promise<Preference> {
  return requestV1<Preference>('/profile/preference', { init: jsonInit('PUT', payload) })
}

/** 列出资料修订，最新在前。 */
export function listRevisions(limit = 20): Promise<Revision[]> {
  return requestV1<Revision[]>(`/profile/revisions?limit=${limit}`)
}

/**
 * 对当前事实创建一份不可变修订快照。
 *
 * 说明:
 *    修订会在"生成简历、发起匹配、确认重要变更"时被引用，是匹配与简历可复现的前提；
 *    它不是每次编辑都创建，因此界面只在用户显式点击时调用。
 */
export function createRevision(reason: string): Promise<Revision> {
  return requestV1<Revision>('/profile/revisions', { init: jsonInit('POST', { reason }) })
}

/** 构造 JSON 请求体；统一在此设置 Content-Type，避免每处调用重复。 */
function jsonInit(method: string, payload: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }
}
