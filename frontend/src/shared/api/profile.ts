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

import { API_V1_PREFIX, ApiError, requestV1, unwrapResponse } from './client'
import type { EditableResource } from './types'

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
  experience_summary?: string | null
  name: string
  role: string | null
  description: string | null
  achievements: string | null
  tech_stack: string[]
  url: string | null
  start_date: string | null
  end_date: string | null
  /** 可选：所属工作经历；个人项目为 null。 */
  experience_id: string | null
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
  target_roles?: string[]
  hard_limits?: HardLimits
  priority_rules?: PriorityRule[]
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

/**
 * 候选条目的来源。
 *
 * `RESUME` 表示内容来自简历原文（必须带摘录，预览阶段逐字校验）；
 * `MANUAL` 表示本人填写（用户新增，或把内容改到摘录之外），不携带摘录。
 * 两类都只是「用户认可可用」的档案事实，不代表已独立核实。
 */
export type ItemOrigin = 'RESUME' | 'MANUAL'

/** AI 从上传简历提取的待确认条目；摘录用于人工比对，并非已核验事实。 */
export interface SourcedSkill {
  origin: ItemOrigin
  source_quote: string | null
  name: string
  /** 导入时系统建议、核对时用户可改；不代表原文证据。 */
  category?: string | null
}
export interface SourcedExperience {
  origin: ItemOrigin
  source_quote: string | null
  company: string
  title: string
  start_date: string
  end_date: string | null
  location: string | null
  responsibilities: string | null
  achievements: string | null
}
export interface SourcedProject {
  origin: ItemOrigin
  source_quote: string | null
  name: string
  role: string | null
  description: string | null
  responsibilities: string | null
  achievements: string | null
  tech_stack: string[]
  url: string | null
  start_date: string | null
  end_date: string | null
}
export interface SourcedEducation {
  origin: ItemOrigin
  source_quote: string | null
  school: string
  major: string | null
  degree: string | null
  start_date: string | null
  end_date: string | null
}
export interface ProfileImportCandidate {
  full_name: string
  name_quote: string
  headline: string | null
  summary: string | null
  email: string | null
  phone: string | null
  city: string | null
  links: ProfileLink[]
  skills: SourcedSkill[]
  experiences: SourcedExperience[]
  projects: SourcedProject[]
  educations: SourcedEducation[]
}
/** 预览覆盖情况；PARTIAL 表示模型有条目或字段未进入待确认候选。 */
export interface ProfileImportCompleteness {
  status: 'COMPLETE' | 'PARTIAL'
  valid_item_count: number
  rejected_item_count: number
  unmapped_field_count: number
  excluded_field_count: number
}
/** 单个模型条目因结构或证据不可信而未进入候选。 */
export interface ProfileImportRejectedItem {
  group: string
  index: number
  code: 'SCHEMA_INVALID' | 'EVIDENCE_INVALID'
  fields: string[]
  message: string
}
/** 模型输出存在当前事实库未支持的字段；字段不会被静默作为事实导入。 */
export interface ProfileImportWarning {
  group: string
  index: number
  code: 'UNMAPPED_MODEL_FIELD' | 'FIELD_NOT_IN_QUOTE' | 'FIELD_ALIAS_MAPPED'
  fields: string[]
  message: string
}
export interface ProfileImportPreview {
  filename: string
  source_hash: string
  candidate: ProfileImportCandidate
  completeness: ProfileImportCompleteness
  rejected_items: ProfileImportRejectedItem[]
  warnings: ProfileImportWarning[]
  /** 为 true 表示候选来自内置开发夹具（未调用大模型服务），不是真实抽取结果。 */
  fixture: boolean
}
export interface ProfileImportResult {
  profile_id: string
  created_profile: boolean
  skills_added: number
  experiences_added: number
  projects_added: number
  educations_added: number
  /** 本次写入的条目中按「本人填写」记录来源的条数（用户新增或改到摘录之外）。 */
  manual_item_count: number
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
  achievements?: string | null
  tech_stack?: string[]
  url?: string | null
  start_date?: string | null
  end_date?: string | null
  experience_id?: string | null
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
  target_roles?: string[]
  hard_limits?: HardLimits
  priority_rules?: PriorityRule[]
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

/** 硬限制必须主动启用，历史偏好默认仍是软偏好。 */
export interface HardLimits { location: boolean; employment_type: boolean; remote: boolean; salary: boolean; salary_basis: 'GROSS' | 'NET' | null }
/** 优先关注不加分，也不覆盖排除规则。 */
export interface PriorityRule { id: string; kind: 'COMPANY_NAME' | 'COMPANY_INDUSTRY' | 'JD_KEYWORD'; value: string; enabled: boolean }

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
  remove: (id: string, version: number) => Promise<{ id: string }>
}

/** 构造一类事实的写操作集合。 */
export function createFactApi<TRead, TPayload>(path: string): FactApi<TRead, TPayload> {
  return {
    create: (payload) => requestV1<TRead>(path, { init: jsonInit('POST', payload) }),
    update: (id, payload) => requestV1<TRead>(`${path}/${id}`, { init: jsonInit('PATCH', payload) }),
    // 证据的 DELETE 在后端实现为归档（写 archived_at），方法名保持 remove 以免界面层假设是物理删除。
    remove: (id, version) => requestV1<{ id: string }>(`${path}/${id}?version=${version}`, { init: { method: 'DELETE' } }),
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

/** 明确同意后发送已上传文件；后端本地抽取文字，AI 候选此时不落库。 */
export function previewProfileImport(filename: string, contentBase64: string, confirmExternal: boolean): Promise<ProfileImportPreview> {
  return requestV1<ProfileImportPreview>('/profile/import-preview', {
    timeoutMs: 90_000,
    init: jsonInit('POST', { filename, content_base64: contentBase64, confirm_external: confirmExternal }),
  })
}

/** 后端确认过的导入阶段；长时间等待模型时不会假装已有百分比。 */
export type ProfileImportStage =
  | 'received' | 'document_parsed' | 'model_resolved' | 'ai_request_started'
  | 'ai_request_retrying' | 'ai_response_parsed' | 'candidate_validated'

const importStages: ReadonlySet<string> = new Set<ProfileImportStage>([
  'received', 'document_parsed', 'model_resolved', 'ai_request_started', 'ai_request_retrying', 'ai_response_parsed', 'candidate_validated',
])

/** 预览过程的进度回调：上传字节与后端阶段分别上报。 */
export interface ProfileImportStreamHandlers {
  /** 后端已完成的处理阶段码。 */
  onStage: (stage: ProfileImportStage) => void
  /**
   * 请求体上传进度（已发送字节 / 总字节）。
   *
   * 只有浏览器给出可计算的总量时才会回调：没有真实分母时宁可不上报，也不给假百分比。
   */
  onUploadProgress?: (loaded: number, total: number) => void
}

/** 单次预览的最长等待时间；与后端 SSE 的 15 秒保活相比留足余量。 */
const IMPORT_STREAM_TIMEOUT_MS = 90_000

/**
 * 同一次请求中读取上传进度、SSE 阶段与最终统一响应；断流不能当作成功。
 *
 * 参数:
 *     filename: 原始文件名，仅用于后端判断格式。
 *     contentBase64: 简历文件的 base64 内容。
 *     confirmExternal: 用户是否已明确同意把提取文字发往大模型服务。
 *     handlers: 进度回调；`onStage` 报告后端阶段，`onUploadProgress` 报告真实上传字节。
 *
 * 返回:
 *     Promise<ProfileImportPreview>: 待人工核对的候选。
 *
 * 异常:
 *     ApiError: 超时（`TIMEOUT`）、连接失败（`NETWORK_ERROR`）、协议或流异常
 *         （`UNEXPECTED_RESPONSE`），以及后端业务错误（保留后端 `code`/`requestId`）。
 *
 * 注意:
 *     用 `XMLHttpRequest` 而不是 `fetch`：只有前者能上报**真实**的上传字节进度，
 *     `fetch` 无法观察请求体发送过程。百分比只用于上传阶段，模型阶段仍只用真实阶段码。
 *     解析按增量进行（`responseText` 只追加、只消费增量），因此分块到达的事件不会被重复处理。
 */
export function previewProfileImportStream(
  filename: string,
  contentBase64: string,
  confirmExternal: boolean,
  handlers: ProfileImportStreamHandlers,
): Promise<ProfileImportPreview> {
  return new Promise<ProfileImportPreview>((resolve, reject) => {
    const request = new XMLHttpRequest()
    let finished = false
    let consumed = 0
    let buffer = ''

    /** 读取响应头里的请求编号；响应头尚未到达时返回 null，用于给失败补上可追踪编号。 */
    const responseRequestId = (): string | null => request.getResponseHeader('X-Request-ID')

    /** 认领终态：保证 resolve/reject 只发生一次，后续事件全部忽略。 */
    const finishWith = (response: Response): void => {
      if (finished) return
      finished = true
      resolve(unwrapResponse<ProfileImportPreview>(response))
    }

    const failWith = (error: ApiError): void => {
      if (finished) return
      finished = true
      reject(error)
    }

    /** 把一条 SSE 片段转成终态响应；进度事件直接回调，非终态返回 null。 */
    const readBlock = (block: string): Response | null => {
      const event = block.match(/^event: (.+)$/m)?.[1]
      const data = block.match(/^data: (.+)$/m)?.[1]
      if (!event || !data) return null
      let parsed: unknown
      try {
        parsed = JSON.parse(data)
      } catch {
        throw new ApiError({
          code: 'UNEXPECTED_RESPONSE',
          message: '导入进度流格式无效。',
          requestId: responseRequestId(),
        })
      }
      if (event === 'progress' && isRecord(parsed) && typeof parsed['stage'] === 'string' && importStages.has(parsed['stage'])) {
        handlers.onStage(parsed['stage'] as ProfileImportStage)
        return null
      }
      if (event === 'result' || event === 'error') {
        const status = event === 'error' && isRecord(parsed) && typeof parsed['http_status'] === 'number'
          ? parsed['http_status'] : 200
        return new Response(JSON.stringify(parsed), {
          status,
          headers: { 'X-Request-ID': responseRequestId() ?? '' },
        })
      }
      return null
    }

    /** 消费自上次以来新增的响应文本；遇到终态事件时返回它。 */
    const consume = (): Response | null => {
      const text: unknown = request.responseText
      if (typeof text !== 'string') return null
      if (text.length > consumed) {
        buffer += text.slice(consumed)
        consumed = text.length
      }
      buffer = buffer.replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const terminal = readBlock(block)
        if (terminal !== null) return terminal
        boundary = buffer.indexOf('\n\n')
      }
      return null
    }

    /** 增量推送期间的安全入口：解析异常不能从事件回调里逃出。 */
    const pump = (): void => {
      if (finished) return
      try {
        const terminal = consume()
        if (terminal !== null) finishWith(terminal)
      } catch (error: unknown) {
        failWith(
          error instanceof ApiError
            ? error
            : new ApiError({
                code: 'UNEXPECTED_RESPONSE',
                message: '导入进度流格式无效。',
                requestId: responseRequestId(),
              }),
        )
      }
    }

    request.open('POST', `${API_V1_PREFIX}/profile/import-preview-stream`)
    request.setRequestHeader('Content-Type', 'application/json')
    request.setRequestHeader('Accept', 'text/event-stream')
    request.timeout = IMPORT_STREAM_TIMEOUT_MS
    request.upload.onprogress = (event: ProgressEvent): void => {
      // 没有可计算的总量就不上报：否则界面只能显示一个编造的分母。
      if (event.lengthComputable && event.total > 0) {
        handlers.onUploadProgress?.(event.loaded, event.total)
      }
    }
    request.onprogress = pump
    request.onreadystatechange = (): void => {
      // 部分实现只在 readyState=3 时刷新文本；与 onprogress 并存会重复读取，
      // 但消费位置以 `consumed` 为准，重复调用不会重复处理事件。
      if (request.readyState === 3) pump()
    }
    request.onload = (): void => {
      pump()
      if (finished) return
      if (request.status >= 200 && request.status < 300) {
        // 2xx 却没有终态事件：不能当作成功。
        const streaming = (request.getResponseHeader('Content-Type') ?? '').includes('text/event-stream')
        failWith(new ApiError({
          code: 'UNEXPECTED_RESPONSE',
          message: streaming ? '导入进度已中断，未收到最终结果。' : '服务未返回导入进度流。',
          requestId: responseRequestId(),
        }))
        return
      }
      // 非 2xx 交给统一契约解析，保留后端错误码与字段级原因。
      finishWith(new Response(request.responseText, {
        status: request.status,
        headers: { 'X-Request-ID': responseRequestId() ?? '' },
      }))
    }
    request.onerror = (): void => {
      failWith(new ApiError({
        code: 'NETWORK_ERROR',
        message: '无法连接到服务，请确认后端是否已启动。',
        requestId: responseRequestId(),
      }))
    }
    request.ontimeout = (): void => {
      failWith(new ApiError({
        code: 'TIMEOUT',
        message: '生成导入候选超时，请稍后重试。',
        requestId: responseRequestId(),
      }))
    }

    request.send(JSON.stringify({ filename, content_base64: contentBase64, confirm_external: confirmExternal }))
  })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/**
 * 用户逐项核对后重传原文件并确认写入，后端会校验哈希与摘录。
 *
 * 候选由调用方传入而不是复用预览结果：用户可以在预览界面修正内容，
 * 写入的必须是修正后的值；`sourceHash` 仍是预览时那份文件的哈希，用于发现换文件。
 */
export function confirmProfileImport(input: {
  filename: string
  contentBase64: string
  sourceHash: string
  candidate: ProfileImportCandidate
  skillIndices: number[]
  experienceIndices: number[]
  projectIndices: number[]
  educationIndices: number[]
}): Promise<ProfileImportResult> {
  return requestV1<ProfileImportResult>('/profile/import-confirm', {
    timeoutMs: 30_000,
    init: jsonInit('POST', {
      filename: input.filename,
      content_base64: input.contentBase64,
      source_hash: input.sourceHash,
      candidate: input.candidate,
      skill_indices: input.skillIndices,
      experience_indices: input.experienceIndices,
      project_indices: input.projectIndices,
      education_indices: input.educationIndices,
      confirmed: true,
    }),
  })
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


/** 五类归档事实；用于恢复，不参与当前编辑表单。 */
export type ArchivedFactKind = 'skills' | 'experiences' | 'projects' | 'educations' | 'languages'
export interface ArchivedFact extends EditableResource {
  archived_at: string
  name?: string
  company?: string
  title?: string
  school?: string
  language?: string
}
export type ArchivedFacts = Record<ArchivedFactKind, ArchivedFact[]>
/** 浏览已归档的历史事实。 */
export function fetchArchivedFacts(): Promise<ArchivedFacts> {
  return requestV1('/profile/archived-facts')
}
/** 按版本恢复；同名技能冲突时保留归档记录。 */
export function restoreArchivedFact(kind: ArchivedFactKind, id: string, version: number): Promise<ArchivedFact> {
  return requestV1(`/profile/archived-facts/${kind}/${id}/restore`, { init: jsonInit('POST', { version }) })
}
/** 按 ID 读取固定修订；不以当前档案替换旧输入。 */
export function fetchRevision(id: string): Promise<Revision> {
  return requestV1(`/profile/revisions/${id}`)
}
