/**
 * Resume 领域的接口调用与类型。
 *
 * 类型是后端 schema 的**手工镜像**（对应 `backend/app/modules/resume/schemas.py`）：只写界面实际
 * 用到的字段，不追求逐字复制。手工维护的代价是后端改字段时前端不会自动报错，因此每个类型都标注了
 * 来源；后端契约变更时必须回来核对这里。
 *
 * 本模块只声明"路径 + 方法 + 类型"，不做业务判断：
 * - 版本不可变、候选稿确认后才产生版本、文档中的事实引用必须能在该修订中找到——全部由后端裁决；
 * - 前端只负责把后端返回的错误码与字段级原因呈现出来（`parseServerError`）。
 */

import { requestV1 } from './client'
import type { EditableResource } from './types'

// --------------------------------------------------------------------------------------------
// 枚举：取值必须与 backend/app/modules/resume/enums.py 一致，否则会在服务端被 CHECK 约束拒绝
// --------------------------------------------------------------------------------------------

/** 简历方向的状态。 */
export type ResumeStatus = 'ACTIVE' | 'ARCHIVED'

/** 候选稿状态。`FAILED` 由后续 AI 生成流程写入，界面只做展示。 */
export type DraftStatus = 'DRAFT' | 'CONFIRMED' | 'DISCARDED' | 'FAILED'

/**
 * 简历模块。
 *
 * 这六项是**固定集合**：`section_order` 必须恰好是它们的一个排列（后端有校验），
 * 因此界面不能增删模块，只能调整顺序与显隐。
 */
export type ResumeSection = 'SUMMARY' | 'EXPERIENCES' | 'PROJECTS' | 'SKILLS' | 'EDUCATIONS' | 'LANGUAGES'

// --------------------------------------------------------------------------------------------
// 文档结构：对应 backend/app/modules/resume/schemas.py 的 ResumeDocument
// --------------------------------------------------------------------------------------------

/** 简历上的公开链接。 */
export interface ResumeLink {
  label: string
  url: string
}

/** 联系方式；构建 AI 输入时应整体剔除，因此与 `basics` 分开存放。 */
export interface ResumeContact {
  email: string | null
  phone: string | null
}

/** 简历头部信息。 */
export interface ResumeBasics {
  full_name: string
  headline: string | null
  city: string | null
  links: ResumeLink[]
}

/** 带溯源的文本块，例如个人简介。 */
export interface ResumeTextBlock {
  text: string
  /** 正文所依据的档案事实主键；手写内容可以为空。 */
  source_fact_id: string | null
}

/** 简历上的一段工作经历。 */
export interface ResumeExperienceItem {
  source_fact_id: string | null
  company: string
  title: string
  location: string | null
  start_date: string | null
  end_date: string | null
  highlights: string[]
}

/** 简历上的一个项目。 */
export interface ResumeProjectItem {
  source_fact_id: string | null
  name: string
  role: string | null
  description: string | null
  tech_stack: string[]
  url: string | null
}

/** 简历上的一项技能。 */
export interface ResumeSkillItem {
  source_fact_id: string | null
  name: string
  category: string | null
  proficiency: string | null
}

/** 简历上的一段教育经历。 */
export interface ResumeEducationItem {
  source_fact_id: string | null
  school: string
  major: string | null
  degree: string | null
  start_date: string | null
  end_date: string | null
}

/** 简历上的一项语言能力。 */
export interface ResumeLanguageItem {
  source_fact_id: string | null
  language: string
  level: string | null
}

/**
 * 简历文档。
 *
 * 模块顺序与显隐属于文档内容而不是数据库列：它们随模板与简历方向变化，
 * 不需要被查询或约束，放进文档可以让历史版本保持自洽。
 *
 * 注意:
 *    文档是**自包含**的（熟练度、链接用可读文本，不复用档案的枚举），
 *    因此这里不引用 `shared/api/profile.ts` 的任何枚举类型。
 */
export interface ResumeDocument {
  schema_version: 1
  basics: ResumeBasics
  contact: ResumeContact | null
  summary: ResumeTextBlock | null
  experiences: ResumeExperienceItem[]
  projects: ResumeProjectItem[]
  skills: ResumeSkillItem[]
  educations: ResumeEducationItem[]
  languages: ResumeLanguageItem[]
  /** 模块展示顺序；必须恰好包含全部六项各一次。 */
  section_order: ResumeSection[]
  /** 不展示的模块；只表达用户的**显式**隐藏，内容保留。 */
  hidden_sections: ResumeSection[]
}

// --------------------------------------------------------------------------------------------
// 响应类型
// --------------------------------------------------------------------------------------------

/** 简历方向；可持续维护的表达单位，不是某次投递的附件。 */
export interface Resume extends EditableResource {
  name: string
  target_direction: string | null
  status: ResumeStatus
}

/** 不可变的简历版本。 */
export interface ResumeVersion {
  id: string
  resume_id: string
  /** 在同一份简历内自增，由服务端确定。 */
  version_no: number
  profile_revision_id: string
  /**
   * 文档内容。
   *
   * 标为 `ResumeDocument` 是"按当前结构解释"的声明：后端刻意不用当前模型重新校验历史版本
   * （`render_schema_version` 才是解释它的开关），因此读取很旧的版本时字段可能与这里的类型不符。
   */
  document_json: ResumeDocument
  render_schema_version: number
  created_reason: string
  created_at: string
  /** 该版本关联的证据主键。 */
  evidence_ids: string[]
}

/** 候选稿；确认前不进入任何正式版本。 */
export interface ResumeDraft extends EditableResource {
  resume_id: string
  /** 改写基线；为空表示从零生成。 */
  base_resume_version_id: string | null
  document_json: ResumeDocument
  status: DraftStatus
  /** 确认后产出的版本主键。 */
  confirmed_resume_version_id: string | null
  generator_name: string
  generator_version: string | null
  failure_code: string | null
  failure_message: string | null
}

// --------------------------------------------------------------------------------------------
// 请求体类型
// --------------------------------------------------------------------------------------------

/** 创建简历方向的请求体。 */
export interface ResumeCreateInput {
  name: string
  target_direction?: string | null
}

/** 局部更新简历方向的请求体；`version` 必须原样回传。 */
export interface ResumeUpdateInput {
  version: number
  name?: string
  target_direction?: string | null
  status?: ResumeStatus
}

/** 创建版本的请求体；`version_no` 与 `render_schema_version` 由服务端确定，不在此提交。 */
export interface ResumeVersionCreateInput {
  profile_revision_id: string
  document: ResumeDocument
  created_reason: string
  evidence_ids?: string[]
}

/** 创建候选稿的请求体。 */
export interface ResumeDraftCreateInput {
  document: ResumeDocument
  base_resume_version_id?: string | null
  generator_name?: string
  generator_version?: string | null
}

/**
 * 就地修改候选稿的请求体。
 *
 * 提交的是**整份文档**而不是局部字段：文档是自包含整体，"删掉一条经历"只能通过提交
 * 不含该条目的完整文档来表达。
 */
export interface ResumeDraftUpdateInput {
  version: number
  document: ResumeDocument
}

/** 确认候选稿的请求体。 */
export interface ResumeDraftConfirmInput {
  version: number
  profile_revision_id: string
  created_reason?: string
  evidence_ids?: string[]
}

// --------------------------------------------------------------------------------------------
// 简历方向
// --------------------------------------------------------------------------------------------

/** 列出简历方向；默认排除已归档的。 */
export function listResumes(includeArchived = false): Promise<Resume[]> {
  return requestV1<Resume[]>(`/resumes?include_archived=${includeArchived}`)
}

/** 创建简历方向。 */
export function createResume(payload: ResumeCreateInput): Promise<Resume> {
  return requestV1<Resume>('/resumes', { init: jsonInit('POST', payload) })
}

/** 读取单个简历方向。 */
export function fetchResume(resumeId: string): Promise<Resume> {
  return requestV1<Resume>(`/resumes/${resumeId}`)
}

/** 局部更新简历方向（改名、改目标方向、改状态）；必须提交当前 `version`。 */
export function updateResume(resumeId: string, payload: ResumeUpdateInput): Promise<Resume> {
  return requestV1<Resume>(`/resumes/${resumeId}`, { init: jsonInit('PATCH', payload) })
}

/**
 * 归档简历方向。
 *
 * 说明:
 *    后端实现为置 `ARCHIVED` 而不是物理删除：历史版本会被投递记录引用，删除会让这些引用失效。
 *    因此方法名用 `archive` 而不是 `remove`。
 */
export function archiveResume(resumeId: string): Promise<Resume> {
  return requestV1<Resume>(`/resumes/${resumeId}`, { init: { method: 'DELETE' } })
}

// --------------------------------------------------------------------------------------------
// 简历版本
// --------------------------------------------------------------------------------------------

/** 列出某份简历的版本；按版本号倒序，最新在前。 */
export function listVersions(resumeId: string, limit = 50): Promise<ResumeVersion[]> {
  return requestV1<ResumeVersion[]>(`/resumes/${resumeId}/versions?limit=${limit}`)
}

/** 创建版本；文档中的事实引用必须能在 `profile_revision_id` 指向的修订中找到。 */
export function createVersion(resumeId: string, payload: ResumeVersionCreateInput): Promise<ResumeVersion> {
  return requestV1<ResumeVersion>(`/resumes/${resumeId}/versions`, { init: jsonInit('POST', payload) })
}

/** 按主键读取版本；投递记录只持有版本主键，因此需要这个不经过简历的入口。 */
export function fetchVersion(versionId: string): Promise<ResumeVersion> {
  return requestV1<ResumeVersion>(`/resume-versions/${versionId}`)
}

// --------------------------------------------------------------------------------------------
// 候选稿
// --------------------------------------------------------------------------------------------

/**
 * 列出某份简历的候选稿。
 *
 * 参数:
 *     resumeId: 简历主键。
 *     status: 只返回该状态；缺省返回全部。
 *     limit: 返回条数上限。
 */
export function listDrafts(resumeId: string, status?: DraftStatus, limit = 50): Promise<ResumeDraft[]> {
  const query = new URLSearchParams({ limit: String(limit) })
  if (status !== undefined) {
    query.set('status', status)
  }
  return requestV1<ResumeDraft[]>(`/resumes/${resumeId}/drafts?${query.toString()}`)
}

/**
 * 按主键读取候选稿。
 *
 * 编辑器与预览都以它为唯一数据来源：让客户端拉取列表再自行筛选，会在候选稿数量超过列表上限时
 * 变成"这条记录明明存在却打不开"，而那个失败与权限、网络都无关，很难排查。
 */
export function fetchDraft(resumeId: string, draftId: string): Promise<ResumeDraft> {
  return requestV1<ResumeDraft>(`/resumes/${resumeId}/drafts/${draftId}`)
}

/** 创建候选稿；确认前不影响任何正式版本。 */
export function createDraft(resumeId: string, payload: ResumeDraftCreateInput): Promise<ResumeDraft> {
  return requestV1<ResumeDraft>(`/resumes/${resumeId}/drafts`, { init: jsonInit('POST', payload) })
}

/**
 * 就地修改待确认的候选稿。
 *
 * 异常:
 *     ApiError：候选稿已确认或已丢弃时 `code` 为 `CONFLICT`（状态检查先于版本检查），
 *     版本过期同样是 `CONFLICT` 但字段级原因指向 `version`。
 */
export function updateDraft(resumeId: string, draftId: string, payload: ResumeDraftUpdateInput): Promise<ResumeDraft> {
  return requestV1<ResumeDraft>(`/resumes/${resumeId}/drafts/${draftId}`, { init: jsonInit('PATCH', payload) })
}

/** 确认候选稿并生成一个不可变版本；同一候选稿只能确认一次。 */
export function confirmDraft(
  resumeId: string,
  draftId: string,
  payload: ResumeDraftConfirmInput,
): Promise<ResumeVersion> {
  return requestV1<ResumeVersion>(`/resumes/${resumeId}/drafts/${draftId}/confirm`, {
    init: jsonInit('POST', payload),
  })
}

/** 丢弃候选稿；不生成版本，已确认的候选稿不能再丢弃。 */
export function discardDraft(resumeId: string, draftId: string, version: number): Promise<ResumeDraft> {
  return requestV1<ResumeDraft>(`/resumes/${resumeId}/drafts/${draftId}/discard`, {
    init: jsonInit('POST', { version }),
  })
}

/** 构造 JSON 请求体；统一在此设置 Content-Type，避免每处调用重复。 */
function jsonInit(method: string, payload: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }
}
