<script setup lang="ts">
/**
 * 从已有简历导入：入口只是主按钮，真正的外发告知与确认收在弹窗里。
 *
 * 数据真实性边界：
 * - 预览阶段只在内存里持有候选，不写库；确认接口才会落库。
 * - 候选可逐字段修正，但 `source_quote`（原文摘录）保持只读——它是来源凭证，允许编辑
 *   就等于允许伪造来源。被改到摘录之外的条目在确认时改挂"本人陈述"证据，由后端裁决。
 *
 * 布局约定：
 * - 基本信息用 `ProfileBasicsSection` + `ProfileLinksField` 渲染——与"创建个人档案"表单是同一个
 *   组件、同一套字段定义（含个人简介与公开链接），因此两处的字段顺序、标签、帮助文本、控件与
 *   网格布局不存在"各自演化"的可能。
 * - 四类候选和手动编辑都由 `ProfileFactSections` 渲染，无候选勾选框；每条原文摘录在
 *   对应卡片底部展示，但目前只具备条目级来源，不能声称每个字段都有独立出处。
 * - 已有档案时，个人简介与公开链接属于"不覆盖的根信息"：字段照常显示但禁用（见 `apply()`），
 *   避免用户填了却在确认时被静默丢弃。
 */

import { computed, nextTick, ref } from 'vue'

import {
  confirmProfileImport,
  previewProfileImportStream,
  type ProfileImportCandidate,
  type ProfileImportPreview,
  type ProfileImportStage,
  type ProfileLink,
} from '@/shared/api/profile'
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { focusFormTarget, notifyFormIssue } from '@/shared/feedback/formNotice'
import { createLocalError, type ParsedServerError } from '@/shared/forms/serverErrors'

import { IMPORT_BASIC_FIELDS, type BasicFieldName, type ImportBasicFieldName } from '../basicsFields'
import { deviatesFromQuote, originOf, quoteOf } from '../candidateOrigin'
import { incompleteLinks, submittableLinks } from '../links'
import { PROFILE_FACT_SECTIONS, type ProfileFactField, type ProfileFactKey, type ProfileFactSection } from '../profileFormFields'
import ProfileBasicsSection from './ProfileBasicsSection.vue'
import ProfileFactSections from './ProfileFactSections.vue'
import ProfileLinksField from './ProfileLinksField.vue'

withDefaults(
  defineProps<{
    /** 是否已有个人档案：为 true 时导入只能补充事实，不覆盖根信息。 */
    hasProfile: boolean
    /**
     * 是否显示面板自带的入口按钮与隐私说明。
     *
     * 页面已经有「从已有简历导入」按钮时传 false：同一入口出现两次会让人以为点错了地方。
     * 隐藏入口不会丢失告知——弹窗内的发送范围说明与"继续即同意"覆盖同一范围。
     */
    showEntry?: boolean
  }>(),
  { showEntry: true },
)
const emit = defineEmits<{
  /** 确认导入成功，页面应重新加载档案聚合。 */
  changed: []
}>()

type CandidateSectionKey = ProfileFactKey
/** 候选条目在界面上按普通字典读写：字段名与后端契约一致，逐字段收窄只在取值处做。 */
type CandidateItem = Record<string, unknown>
type CandidateField = ProfileFactField
/** 两条路径共用同一份事实字段定义。 */
const SECTIONS = PROFILE_FACT_SECTIONS

const fileInput = ref<HTMLInputElement | null>(null)
const modalOpen = ref(false)
const file = ref<File | null>(null)
const contentBase64 = ref('')
/** 服务端返回的预览（原文件哈希等），写入时仍以它为准做换文件校验。 */
const preview = ref<ProfileImportPreview | null>(null)
/** 用户可编辑的候选副本；与 `preview.candidate` 分离，避免改动污染原始预览。 */
const draft = ref<ProfileImportCandidate | null>(null)
/** 上传解析后的核对弹窗；关闭不丢草稿，确认成功后才清空。 */
const reviewOpen = ref(false)
const busyPreview = ref(false)
const progressStage = ref<ProfileImportStage | 'reading_file'>('reading_file')
/** 请求体已发送/总字节；只由传输层上报的真实进度驱动，不用它推算模型阶段。 */
const uploadLoaded = ref(0)
const uploadTotal = ref(0)
const busyConfirm = ref(false)
/** 本地校验与服务端失败共用一个提示位置；无法定位字段的失败走全局通知。 */
const error = ref<ParsedServerError | null>(null)
const candidateErrors = ref<Record<string, string>>({})
const basicErrors = ref<Record<string, string>>({})
const reviewForm = ref<HTMLElement | null>(null)
const result = ref('')
const selected = ref<Record<CandidateSectionKey, number[]>>({
  skills: [],
  experiences: [],
  projects: [],
  educations: [],
})
/** 仅为展示追加原摘录；写入仍使用无附加字段的原始候选。 */
const formItems = computed<Record<CandidateSectionKey, CandidateItem[]>>(() => ({
  skills: itemsOf('skills').map((item) => ({ ...item, original_source_quote: originalQuoteOf(item) })),
  experiences: itemsOf('experiences').map((item) => ({ ...item, original_source_quote: originalQuoteOf(item) })),
  projects: itemsOf('projects').map((item) => ({ ...item, original_source_quote: originalQuoteOf(item) })),
  educations: itemsOf('educations').map((item) => ({ ...item, original_source_quote: originalQuoteOf(item) })),
}))
const busy = computed(() => busyPreview.value || busyConfirm.value)
/**
 * 只有选了文件才允许"继续"。
 *
 * 外发同意由弹窗内的红色告知文案 + 用户主动点击「继续」构成：告知已经展示在按钮旁边，
 * 再加一个勾选框只是多一步操作，不增加实际的知情程度。
 */
const canContinue = computed(() => file.value !== null && error.value === null && !busy.value)
const confirmLabel = computed(() => '确认保存导入内容')
const progressText = computed(() => ({
  reading_file: '正在读取文件…',
  received: '请求已送达，正在解析文档…',
  document_parsed: '文档解析完成，正在读取模型配置…',
  model_resolved: '模型配置已读取，准备生成候选…',
  ai_request_started: '大模型服务正在生成候选，通常需要几十秒…',
  ai_request_retrying: '大模型服务短暂不可用，正在自动重试一次…',
  ai_response_parsed: '模型已返回，正在校验候选结构和原文摘录…',
  candidate_validated: '候选已校验，正在展示预览…',
})[progressStage.value])

/** 上传阶段的真实百分比；总量未知时为 0，界面据此回退到阶段文案。 */
const uploadPercent = computed(() =>
  uploadTotal.value > 0 ? Math.min(100, Math.round((uploadLoaded.value / uploadTotal.value) * 100)) : 0,
)
/** 只在仍在发送请求体时显示进度条：上传完成后继续显示 100% 会掩盖模型阶段。 */
const showUploadProgress = computed(
  () => busyPreview.value && uploadTotal.value > 0 && uploadPercent.value < 100,
)

/** 局部候选必须明确说明遗漏，不能让用户把可确认条目误认为整份简历已被完整抽取。 */
const partialPreviewMessage = computed(() => {
  const current = preview.value
  if (current === null || current.completeness.status !== 'PARTIAL') return ''
  const { valid_item_count, rejected_item_count, unmapped_field_count, excluded_field_count } = current.completeness
  const parts = [`本次仅生成部分可验证候选：${valid_item_count} 条可核对`]
  if (rejected_item_count > 0) parts.push(`${rejected_item_count} 条因格式或证据不足未纳入`)
  if (unmapped_field_count > 0) parts.push(`${unmapped_field_count} 个未映射字段未导入`)
  if (excluded_field_count > 0) parts.push(`${excluded_field_count} 个字段缺少原文证据而未导入`)
  return `${parts.join('，')}。请检查下方遗漏说明或手工补录。`
})

/**
 * 内置夹具提示。
 *
 * 夹具数据不是真实模型抽取结果，必须显式说明，否则用户会把自己的档案填成样例数据。
 */
const fixtureNotice = computed(() =>
  preview.value?.fixture === true
    ? '当前为内置模拟数据（未调用大模型服务）：内容来自内置样例，仅用于联调导入流程，不代表你的简历。'
    : '',
)

/** 失败提示的补充说明；本地校验没有错误编号，因此只在有值时展示。 */
const errorDescription = computed(() => {
  if (error.value === null) {
    return undefined
  }
  const parts = [...error.value.general]
  if (error.value.requestId !== null) {
    parts.push(`错误编号：${error.value.requestId}`)
  }
  return parts.length === 0 ? undefined : parts.join(' ')
})

function openModal(): void {
  error.value = null
  if (draft.value !== null) reviewOpen.value = true
  else modalOpen.value = true
}

/**
 * 供父页面在"选择从已有简历导入"时直接打开弹窗。
 *
 * 暴露动作而不是内部状态：页面无需知道弹窗由哪个 ref 控制，也就不会绕过弹窗内的外发告知。
 */
defineExpose({ open: openModal })

/** 生成过程中不允许关闭：请求仍在进行，关闭会让"取消"与"结果"产生歧义。 */
function closeModal(): void {
  if (busyPreview.value) return
  modalOpen.value = false
}

function chooseFile(): void {
  fileInput.value?.click()
}

/** 只有选定合法新文件才清除旧候选；取消文件选择仍可回到原草稿。 */
function onFileChange(event: Event): void {
  const target = event.target as HTMLInputElement
  const next = target.files?.[0] ?? null
  target.value = ''
  if (!next) return
  if (!/\.(pdf|html|htm)$/i.test(next.name) || next.size === 0 || next.size > 3 * 1024 * 1024) {
    error.value = createLocalError('请选择不超过 3 MB 的 PDF 或 HTML 简历文件。')
    notifyFormIssue({ kind: 'warning', title: '文件不符合要求', detail: error.value.message, key: 'profile-import-file' })
    return
  }
  contentBase64.value = ''
  preview.value = null
  draft.value = null
  result.value = ''
  error.value = null
  file.value = next
}

function encodeFile(selectedFile: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('文件读取失败。'))
        return
      }
      resolve(reader.result.split(',', 2)[1] ?? '')
    }
    reader.onerror = () => reject(new Error('文件读取失败。'))
    reader.readAsDataURL(selectedFile)
  })
}

/**
 * 深拷贝候选作为编辑草稿。
 *
 * 用 JSON 往返而不是共享引用：`preview.candidate` 必须保持服务端返回的原样，
 * 否则"用户改过什么"就无从判断，往后端传的错误内容也无法与预览对照。
 */
function cloneCandidate(candidate: ProfileImportCandidate): ProfileImportCandidate {
  return JSON.parse(JSON.stringify(candidate)) as ProfileImportCandidate
}

/**
 * 生成预览。
 *
 * 点击「继续」即视为对外发的明确同意（告知文案就在按钮上方），因此这里固定传 `true`；
 * 没有选择文件时不发起任何外发请求。
 */
async function generate(): Promise<void> {
  if (!file.value || busy.value) return
  busyPreview.value = true
  progressStage.value = 'reading_file'
  error.value = null
  result.value = ''
  try {
    contentBase64.value = await encodeFile(file.value)
    uploadLoaded.value = 0
    uploadTotal.value = 0
    const next = await previewProfileImportStream(file.value.name, contentBase64.value, true, {
      onStage: (stage) => {
        progressStage.value = stage
      },
      onUploadProgress: (loaded, total) => {
        uploadLoaded.value = loaded
        uploadTotal.value = total
      },
    })
    preview.value = next
    draft.value = cloneCandidate(next.candidate)
    candidateErrors.value = {}
    basicErrors.value = {}
    linksError.value = null
    rememberOriginalQuotes(draft.value)
    selected.value = {
      skills: next.candidate.skills.map((_, index) => index),
      experiences: next.candidate.experiences.map((_, index) => index),
      projects: next.candidate.projects.map((_, index) => index),
      educations: next.candidate.educations.map((_, index) => index),
    }
    // 上传弹窗关闭，填充后的共享表单在独立核对弹窗中展示；此时绝不写库。
    modalOpen.value = false
    reviewOpen.value = true
  } catch (cause: unknown) {
    // 文件读取失败是本地问题，需要就地提示；服务端失败中无法定位字段的走全局通知。
    error.value = cause instanceof Error && cause.message === '文件读取失败。'
      ? createLocalError(cause.message) : resolveActionFailure(cause, '生成导入候选')
    if (error.value) notifyFormIssue({ kind: 'error', title: '生成候选失败', detail: error.value.message, key: 'profile-import-preview-error' })
  } finally {
    busyPreview.value = false
  }
}

/**
 * 候选条目的来源与"是否仍落在摘录内"的判断。
 *
 * `MANUAL` 条目在契约上不允许携带摘录，因此改成本人填写时要清掉 `source_quote`；
 * 原始摘录另行记在 `originalQuotes` 里，仅供用户对照查看（不参与提交）。
 */
const originalQuotes = new WeakMap<CandidateItem, string>()

const SECTION_BY_KEY = new Map<CandidateSectionKey, ProfileFactSection>(
  SECTIONS.map((section) => [section.key, section]),
)

/** 各分组的条数上限，与后端模型一致；超限就地拦住，避免确认时才收到 422。 */
const COLLECTION_LIMITS: Record<CandidateSectionKey, number> = {
  skills: 40,
  experiences: 20,
  projects: 20,
  educations: 20,
}

/** 用户新增条目的初始形态：来源为本人填写，字段留空由用户补全，不伪造任何取值。 */
const BLANK_ITEMS: Record<CandidateSectionKey, () => CandidateItem> = {
  skills: () => ({ origin: 'MANUAL', source_quote: null, name: '' }),
  experiences: () => ({
    origin: 'MANUAL',
    source_quote: null,
    company: '',
    title: '',
    location: null,
    start_date: null,
    end_date: null,
    responsibilities: null,
    achievements: null,
  }),
  projects: () => ({
    origin: 'MANUAL',
    source_quote: null,
    name: '',
    role: null,
    description: null,
    responsibilities: null,
    achievements: null,
    tech_stack: [],
    url: null,
    start_date: null,
    end_date: null,
  }),
  educations: () => ({
    origin: 'MANUAL',
    source_quote: null,
    school: '',
    major: null,
    degree: null,
    start_date: null,
    end_date: null,
  }),
}

/** 原始摘录：改成本人填写后仍可对照查看，但不参与提交。 */
function originalQuoteOf(item: CandidateItem): string {
  return originalQuotes.get(item) ?? ''
}

/**
 * 把条目改按「本人填写」记录来源。
 *
 * 清掉摘录是契约要求：`MANUAL` 条目携带摘录会被后端拒绝（防止用一段原文给编造内容做背书）。
 * 原始摘录先存下来，界面上继续给用户看，只是标明它已不再是来源。
 */
function markManual(item: CandidateItem): void {
  const quote = quoteOf(item)
  if (quote !== '') originalQuotes.set(item, quote)
  item['origin'] = 'MANUAL'
  item['source_quote'] = null
}

/** 取出用于摘录比对的两类取值：文字/技术栈取值，以及日期里的年份。 */
function quoteCheckInputs(
  section: ProfileFactSection,
  item: CandidateItem,
): { values: string[]; years: string[] } {
  const values: string[] = []
  const years: string[] = []
  for (const field of section.fields) {
    if (field.kind === 'tags') {
      values.push(...tagsOf(item, field.name))
    } else if (field.kind === 'date') {
      const text = textOf(item, field.name)
      if (text !== '') years.push(text.slice(0, 4))
    } else {
      values.push(textOf(item, field.name))
    }
  }
  if (section.key === 'projects') values.push(textOf(item, 'responsibilities'), textOf(item, 'achievements'))
  return { values, years }
}

/** 条目改动后重新判断来源：改到摘录之外就转成「本人填写」，并保留原始摘录供查看。 */
function refreshOrigin(key: CandidateSectionKey, index: number): void {
  const section = SECTION_BY_KEY.get(key)
  const items = draft.value?.[key] as unknown as CandidateItem[] | undefined
  const item = items?.[index]
  if (section === undefined || item === undefined) return
  if (originOf(item) === 'MANUAL') return
  const { values, years } = quoteCheckInputs(section, item)
  if (deviatesFromQuote(values, years, quoteOf(item))) {
    markManual(item)
  }
}

/** 预览生成后记录每条 AI 条目的原始摘录，供用户改成本人填写后对照。 */
function rememberOriginalQuotes(candidate: ProfileImportCandidate): void {
  for (const section of SECTIONS) {
    const items = candidate[section.key] as unknown as CandidateItem[]
    for (const item of items) {
      const quote = quoteOf(item)
      if (quote !== '') originalQuotes.set(item, quote)
    }
  }
}

/** 在分组末尾新增一条本人填写的空条目；保留在表单中的完整条目参与确认。 */
function addItem(key: CandidateSectionKey): void {
  const candidate = draft.value
  if (candidate === null) return
  const items = candidate[key] as unknown as CandidateItem[]
  if (items.length >= COLLECTION_LIMITS[key]) {
    error.value = createLocalError(
      `${SECTION_BY_KEY.get(key)?.title ?? key}最多 ${COLLECTION_LIMITS[key]} 条。`,
    )
    notifyFormIssue({ kind: 'warning', title: '条目数量已达上限', detail: error.value.message, key: `profile-import-limit-${key}` })
    return
  }
  items.push(BLANK_ITEMS[key]())
  selected.value[key] = [...selected.value[key], items.length - 1]
}

/**
 * 从候选中删除一条条目（技能与其它事实共用）。
 *
 * 删除后必须重建选择下标：下标是提交给后端的契约，不重建会把剩下的条目错位提交。
 * 确认接口仍使用下标契约，这里同步调整下标避免错位。
 */
function removeItem(key: CandidateSectionKey, index: number): void {
  const candidate = draft.value
  if (candidate === null) return
  const items = candidate[key] as unknown as CandidateItem[]
  if (index < 0 || index >= items.length) return
  items.splice(index, 1)
  candidateErrors.value = {}
  error.value = null
  selected.value[key] = selected.value[key]
    .filter((value) => value !== index)
    .map((value) => (value > index ? value - 1 : value))
}

/** 取某个分区的候选条目；草稿尚未生成时返回空数组。 */
function itemsOf(key: CandidateSectionKey): CandidateItem[] {
  const candidate = draft.value
  return candidate === null ? [] : (candidate[key] as unknown as CandidateItem[])
}

function textOf(item: CandidateItem, name: string): string {
  const value = item[name]
  return typeof value === 'string' ? value : ''
}

function tagsOf(item: CandidateItem, name: string): string[] {
  const value = item[name]
  return Array.isArray(value) ? (value as string[]) : []
}

/** 候选契约支持的基本信息字段名集合；判定函数让收窄由类型系统负责，不靠手写断言。 */
const importBasicNames = new Set<string>(IMPORT_BASIC_FIELDS.map((field) => field.name))

function isImportBasicName(name: BasicFieldName): name is ImportBasicFieldName {
  return importBasicNames.has(name)
}

/**
 * 诊断信息里的分组与字段名 → 用户看得懂的中文。
 *
 * 后端用稳定的英文键名（`projects`、`summary`）报告问题，界面直接照搬会变成一句中英混杂的提示；
 * 这里只做显示层映射，接口契约与字段名保持不变。
 */
const DIAGNOSTIC_GROUP_LABELS: Record<string, string> = {
  basics: '基本信息',
  skills: '技能',
  experiences: '工作经历',
  projects: '项目经历',
  educations: '教育经历',
}

const DIAGNOSTIC_FIELD_LABELS: Record<string, string> = {
  summary: '个人简介',
  links: '公开链接',
  role: '角色',
  description: '项目说明',
  responsibilities: '职责',
  achievements: '成果',
  tech_stack: '技术栈',
  url: '链接',
  location: '地点',
  start_date: '开始日期',
  end_date: '结束日期',
}

function diagnosticGroup(group: string): string {
  return DIAGNOSTIC_GROUP_LABELS[group] ?? group
}

function diagnosticFields(fields: readonly string[]): string {
  return fields.map((field) => DIAGNOSTIC_FIELD_LABELS[field] ?? field).join('、')
}

/** 公开链接草稿；候选契约里它是数组字段，由共享组件编辑。 */
const candidateLinks = computed<ProfileLink[]>(() => draft.value?.links ?? [])
/** 链接行错误（只填一半）；与创建档案页共用同一套判断与文案。 */
const linksError = ref<string | null>(null)

function setLinks(next: ProfileLink[]): void {
  const candidate = draft.value
  if (candidate === null) return
  candidate.links = next
  linksError.value = null
  error.value = null
}

/** 写入一个候选字段；空字符串视为清空，与后端"缺失字段留空"的语义一致。 */
function setValue(key: CandidateSectionKey, index: number, field: CandidateField, value: unknown): void {
  const candidate = draft.value
  if (candidate === null) return
  const item = (candidate[key] as unknown as CandidateItem[])[index]
  if (item === undefined) return
  delete candidateErrors.value[`${key}-${index}-${field.name}`]
  error.value = null
  if (field.kind === 'tags') {
    item[field.name] = Array.isArray(value) ? value : []
  } else {
    // 空字符串统一写成 null：不产生"空字符串事实"，与后端确认契约一致。
    const text = typeof value === 'string' ? value : ''
    item[field.name] = text === '' ? null : text
  }
  if (key === 'projects' && field.name === 'description') {
    item['responsibilities'] = null
    item['achievements'] = null
  }
  // 改到摘录之外就当场转成「本人填写」：来源变了要在界面上立刻可见，而不是等确认时才暴露。
  refreshOrigin(key, index)
}

/**
 * 写入一个候选基本信息字段；空字符串视为清空，与后端“缺失字段留空”的语义一致。
 *
 * 共享字段区按传入的 `fields` 触发事件，而候选契约（后端 `ImportCandidate`，`extra="forbid"`）
 * 只包含 5 个字段，因此这里再挡一次：契约外的字段（例如仅创建页有的个人简介）直接忽略，
 * 不会把后端不认的键写进确认请求体。
 */
function setBasic(name: BasicFieldName, value: string): void {
  const candidate = draft.value
  if (candidate === null) return
  if (!isImportBasicName(name)) return
  delete basicErrors.value[name]
  error.value = null
  if (name === 'full_name') {
    // 姓名是候选的最小锚点，不能写 null；留空由提交前的必填校验拦下。
    candidate.full_name = value
  } else {
    candidate[name] = value === '' ? null : value
  }
}

/**
 * 提交前的领域必填校验。
 *
 * 候选允许留空（简历没提供就显示为空），但保留的条目不能带空的必填字段提交。
 * 后端会以领域规则拒绝（422），这里提前指出具体条目，供用户补全或删除。
 */
function firstMissingRequiredField(): { message: string; selector: string; errorKey: string } | null {
  for (const section of SECTIONS) {
    const items = itemsOf(section.key)
    for (const index of selected.value[section.key]) {
      const item = items[index]
      if (item === undefined) continue
      for (const field of section.fields) {
        if (field.required !== true) continue
        if (textOf(item, field.name).trim() === '') {
          return {
            message: `${section.title}第 ${index + 1} 条缺少必填的「${field.label}」：请补全该字段，或删除该条。`,
            selector: `[data-testid="fact-${section.key}-${index}-${field.name}"]`,
            errorKey: `${section.key}-${index}-${field.name}`,
          }
        }
      }
    }
  }
  return null
}

/** 首次校验失败时自动定位具体字段，通知只负责提醒。 */
async function showReviewIssue(message: string, selector: string, title = '请完善表单'): Promise<void> {
  const target = () => reviewForm.value?.querySelector<HTMLElement>(selector) ?? null
  await nextTick()
  focusFormTarget(target())
  notifyFormIssue({ kind: 'warning', title, detail: message, key: 'profile-import-form-warning' })
}

/** 关闭核对弹窗只隐藏视图，候选仍可从标题按钮重新打开。 */
function closeReview(): void {
  if (busyConfirm.value) return
  reviewOpen.value = false
}

/** 用户需要换文件时返回上传弹窗；真正选定新文件后按换文件规则清空旧候选。 */
function chooseAnotherResume(): void {
  reviewOpen.value = false
  modalOpen.value = true
}

/** 用户确认后一次性提交；已有基本资料绝不从候选覆盖。 */
async function apply(): Promise<void> {
  // 取局部快照后再提交：确认过程中这些引用不会被其它分支改写，也避免依赖跨 await 的收窄。
  const currentPreview = preview.value
  const currentDraft = draft.value
  const currentFile = file.value
  linksError.value = null
  if (currentPreview === null || currentDraft === null || currentFile === null || busy.value) return
  if (currentDraft.full_name.trim() === '') {
    error.value = createLocalError('候选姓名为空，无法创建档案：请在核对表单中补全姓名。')
    basicErrors.value.full_name = '该项为必填。'
    await showReviewIssue(error.value.message, '[data-testid="candidate-basics-full_name"]')
    return
  }
  const missing = firstMissingRequiredField()
  if (missing !== null) {
    error.value = createLocalError(missing.message)
    candidateErrors.value[missing.errorKey] = '该项为必填。'
    await showReviewIssue(missing.message, missing.selector)
    return
  }
  if (incompleteLinks(currentDraft.links).length > 0) {
    // 与创建档案页同一套规则与文案：只填一半的行意图不明，提交上去只会得到难懂的嵌套字段错误。
    linksError.value = '每条链接都需要同时填写名称与地址；留空的整行会被忽略。'
    const index = currentDraft.links.findIndex((link) =>
      (link.label.trim() !== '' || link.url.trim() !== '') && (link.label.trim() === '' || link.url.trim() === ''),
    )
    const name = currentDraft.links[index]?.label.trim() === '' ? 'label' : 'url'
    await showReviewIssue(linksError.value, `[data-testid="link-${name}-${index}"]`)
    return
  }
  const payloadCandidate: ProfileImportCandidate = {
    ...currentDraft,
    // 整行留空的链接不参与提交；不就地改草稿，避免用户的输入在界面里凭空消失。
    links: submittableLinks(currentDraft.links),
  }
  const usedFixture = currentPreview.fixture
  busyConfirm.value = true
  error.value = null
  try {
    const saved = await confirmProfileImport({
      filename: currentFile.name,
      contentBase64: contentBase64.value,
      sourceHash: currentPreview.source_hash,
      candidate: payloadCandidate,
      skillIndices: selected.value.skills,
      experienceIndices: selected.value.experiences,
      projectIndices: selected.value.projects,
      educationIndices: selected.value.educations,
    })
    result.value =
      `已${saved.created_profile ? '创建档案并' : ''}导入 ${saved.experiences_added} 段工作经历、`
      + `${saved.projects_added} 个项目经历、${saved.educations_added} 段教育经历和 ${saved.skills_added} 项技能，`
      + '均为“未验证”状态；可在个人资料表单中继续编辑。'
      + (saved.manual_item_count > 0 ? `其中 ${saved.manual_item_count} 条按“本人填写”记录来源。` : '')
      + (usedFixture ? '（本次为内置模拟数据，不是真实模型抽取结果）' : '')
    notifyFormIssue({ kind: 'success', title: '个人档案已更新', detail: result.value, key: 'profile-import-success' })
    preview.value = null
    draft.value = null
    file.value = null
    contentBase64.value = ''
    modalOpen.value = false
    reviewOpen.value = false
    emit('changed')
  } catch (cause: unknown) {
    error.value = resolveActionFailure(cause, '导入简历候选')
    if (error.value) notifyFormIssue({ kind: 'error', title: '保存导入内容失败', detail: error.value.message, key: 'profile-import-save-error' })
  } finally {
    busyConfirm.value = false
  }
}

</script>

<template>
  <div class="import-panel" data-testid="profile-import-panel">
    <!--
      入口只在"面板自己承担入口"时显示：页面已经提供「从已有简历导入」按钮时（showEntry=false），
      再来一个同名按钮会让人以为点错了入口。隐藏入口不丢信息：弹窗里的发送范围说明与"继续即同意"覆盖同一范围。
    -->
    <div v-if="showEntry" class="import-entry">
      <a-button type="primary" data-testid="open-import-modal" @click="openModal">从已有简历导入</a-button>
      <p class="import-privacy">
        简历原文件不会上传或保存在服务端。只有你在弹窗中确认后，才会把本地提取的简历文字发送到已配置的大模型服务
        生成待核对候选；候选经你逐项核对并确认后才会写入个人档案。扫描件（无文字层的 PDF）暂不支持。
      </p>
    </div>
    <a-alert
      v-if="showEntry && hasProfile"
      type="info"
      show-icon
      message="已有档案只补充经历与技能，不覆盖现有基本信息。"
      class="import-notice"
    />

    <!--
      与仓库其它弹窗一致：不用传送门（`:get-container="false"`），测试可以直接在组件树里断言，
      页面也不会留下游离节点。`data-testid` 放在内容上，Modal 会自行处理组件标签上的属性透传。
    -->
    <a-modal
      v-if="modalOpen"
      :open="true"
      :get-container="false"
      :width="640"
      :mask-closable="false"
      :closable="!busyPreview"
      title="从已有简历导入"
      @cancel="closeModal"
    >
      <div data-testid="import-modal">
        <a-alert
          type="info"
          show-icon
          message="发送范围与写入边界"
          description="简历原文件不会上传或保存在服务端；将从 PDF/HTML 本地提取的简历文字发送到已配置的大模型服务，用于生成待核对候选。提取文字可能包含姓名、联系方式与工作经历。候选不会自动写入个人档案：只有你逐项核对并确认后才会落库。"
          class="import-notice"
        />
        <div class="file-row">
          <input
            ref="fileInput"
            class="file-input"
            type="file"
            accept=".pdf,.html,.htm,application/pdf,text/html"
            aria-label="选择 PDF 或 HTML 简历"
            @change="onFileChange"
          />
          <a-button :disabled="busyPreview" data-testid="choose-resume-file" @click="chooseFile">选择简历文件</a-button>
          <span class="file-name">{{ file?.name ?? '尚未选择文件' }}</span>
        </div>
        <!-- 外发提示：小字把"点继续会发生什么"讲清楚，不再要求额外勾选（勾选不增加知情程度）。 -->
        <p class="import-send-notice" data-testid="profile-import-send-notice">
          点击「继续」将把本地提取的简历文字发送到已配置的大模型服务，用于生成待核对候选；短暂的连接或服务错误时最多会自动重试一次
        </p>
        <div v-if="busyPreview" class="import-progress" role="status" aria-live="polite" data-testid="profile-import-progress">
          <!-- 上传阶段按真实字节走；上传完成后换成后端阶段文案，两者不混用同一个数字。 -->
          <div v-if="showUploadProgress" class="upload-row" data-testid="profile-import-upload-progress">
            <span>正在上传简历文件…</span>
            <a-progress :percent="uploadPercent" :show-info="false" class="upload-bar" />
            <span>{{ uploadPercent }}%</span>
          </div>
          <template v-else>
            <a-spin size="small" />
            <span>{{ progressText }}</span>
          </template>
        </div>
        <p v-if="error" class="form-error-summary" role="alert" data-testid="profile-import-error">{{ error.message }} {{ errorDescription }}</p>
      </div>
      <template #footer>
        <a-button :disabled="busyPreview" data-testid="cancel-import" @click="closeModal">取消</a-button>
        <a-button
          type="primary"
          :loading="busyPreview"
          :disabled="!canContinue"
          data-testid="preview-import"
          @click="generate"
        >
          继续
        </a-button>
      </template>
    </a-modal>

    <!-- 上传后的第二个弹窗承载已填充表单；只有它的确认按钮会写入。 -->
    <a-modal
      v-if="reviewOpen && draft"
      :open="true"
      :get-container="false"
      :width="920"
      :mask-closable="false"
      :closable="!busyConfirm"
      title="核对简历导入内容"
      @cancel="closeReview"
    >
    <div ref="reviewForm" class="candidate" data-testid="profile-import-preview">
      <a-divider>待核对内容</a-divider>
      <p class="confirm-notice">请核对下方表单；点击确认后，这些内容会加入个人档案并用于匹配和简历候选。内容均为“未验证”，不代表已独立核实。</p>
      <p v-if="error" class="form-error-summary" role="alert" data-testid="profile-import-error">{{ error.message }} {{ errorDescription }}</p>
      <a-alert
        v-if="partialPreviewMessage"
        type="warning"
        show-icon
        :message="partialPreviewMessage"
        class="import-notice"
        data-testid="profile-import-partial-warning"
      >
        <template #description>
          <ul class="import-diagnostics">
            <li v-for="item in preview?.rejected_items" :key="`rejected-${item.group}-${item.index}`">
              {{ diagnosticGroup(item.group) }} 第 {{ item.index + 1 }} 条：{{ item.message }}
            </li>
            <li
              v-for="(warning, warningIndex) in preview?.warnings"
              :key="`warning-${warningIndex}-${warning.group}-${warning.index}`"
            >
              {{ diagnosticGroup(warning.group) }} 第 {{ warning.index + 1 }} 条（{{
                diagnosticFields(warning.fields)
              }}）：{{ warning.message }}
            </li>
          </ul>
        </template>
      </a-alert>
      <a-alert
        v-if="fixtureNotice"
        type="warning"
        show-icon
        :message="fixtureNotice"
        class="import-notice"
        data-testid="profile-import-fixture-notice"
      />
      <p class="candidate-note">
        以下均是未验证候选，可直接修正、补全、新增或删除条目；摘录只读，它记录内容在原文中的出处。
        AI 提取的条目标注「简历原文」，你新增或改到摘录之外的条目标注「本人填写」——两类都能正常使用，
        都会以“未验证”写入，不需要为新增条目编造原文摘录。
        删除可排除错误条目。简历未提供的可选字段会显示为空，不会写入无意义的空事实。
        简历只写年份或年月时，日期中的缺失月份/日可能以 1 补位，不表示原文提供了精确日期。
        <template v-if="hasProfile">
          已有个人档案：导入只补充事实，个人简介与公开链接不会被导入，请在档案页修改。
        </template>
      </p>

      <!--
        基本信息用与“创建个人档案”完全相同的字段定义与布局组件渲染，不在这里维护第二份模板；
        `candidate-section` 只是把本页的分区间距套上去，字段与网格仍由共享组件决定。
      -->
      <ProfileBasicsSection
        class="candidate-section"
        :fields="IMPORT_BASIC_FIELDS"
        :record="draft"
        :errors="basicErrors"
        :disabled-fields="hasProfile ? ['summary'] : []"
        testid-prefix="candidate-basics"
        @update-field="setBasic"
      >
        <!-- 公开链接与创建档案页共用同一个组件；已有档案时不覆盖，因此禁用而不是隐藏。 -->
        <ProfileLinksField
          :links="candidateLinks"
          :error="linksError"
          :disabled="hasProfile"
          @update-links="setLinks"
        />
        <p class="source-quote profile-field-grid__wide">姓名原文：{{ draft.name_quote }}</p>
      </ProfileBasicsSection>

      <ProfileFactSections
        :items="formItems"
        mode="import"
        :errors="candidateErrors"
        @update-field="setValue"
        @add-item="addItem"
        @remove-item="removeItem"
      />

    </div>
      <template #footer>
        <a-button :disabled="busyConfirm" data-testid="choose-another-resume" @click="chooseAnotherResume">重新选择简历</a-button>
        <a-button :disabled="busyConfirm" data-testid="cancel-review" @click="closeReview">取消</a-button>
        <a-button type="primary" :loading="busyConfirm" data-testid="confirm-import" @click="apply">{{ confirmLabel }}</a-button>
      </template>
    </a-modal>
  </div>
</template>

<style scoped>
.import-panel { margin-bottom: var(--ja-space-section); }
.import-entry { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.import-privacy, .candidate-note { color: var(--ja-color-muted); line-height: 1.65; }
.form-error-summary { margin: 12px 0; color: var(--ja-color-danger); font-size: 13px; line-height: 1.6; }
.import-privacy { flex: 1 1 320px; margin: 0; font-size: 13px; }
.import-empty-hint { margin: 0; color: var(--ja-color-muted); font-size: 13px; line-height: 1.65; }
/* 外发提示：必须一眼看到，因此用危险色而不是弱化色；放在「继续」上方，紧邻用户动作。 */
.import-send-notice { margin: 12px 0 0; color: var(--ja-color-danger); font-size: 12px; line-height: 1.6; }
.file-row { display: flex; align-items: center; gap: 12px; margin: 16px 0; flex-wrap: wrap; }
.file-input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.file-name { color: var(--ja-color-muted); font-size: 13px; overflow-wrap: anywhere; }
.import-actions, .import-notice { margin-top: 16px; }
/* 核对弹窗：正文明确写入后果，供用户作最终判断。 */
.confirm-notice { margin: 0; line-height: 1.65; }
.confirm-hint { margin: 8px 0 0; color: var(--ja-color-muted); font-size: 13px; line-height: 1.6; }
.import-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.import-progress { display: flex; align-items: center; gap: 10px; margin-top: 16px; color: var(--ja-color-muted); }
.upload-row { display: flex; align-items: center; gap: 10px; width: 100%; }
.upload-bar { flex: 1 1 auto; min-width: 0; }
.candidate { margin-top: 20px; }
.candidate-section { margin: 20px 0; }
/* 来源标签：与摘录文案同一行的次要信息，不抢内容本身的注意力。 */
.origin-tag { margin: 0; }
.add-item { margin-top: 8px; }
/* 技能卡：固定一行两列，卡片留出足够高度让技能名醒目、原文出处单独落在下方。 */
.skill-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.skill-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 0 8px;
  padding: 14px 12px 12px 16px;
  border: 1px solid var(--ja-color-border);
  border-radius: var(--ja-radius);
  background: var(--ja-color-surface);
}
/* 技能名是这张卡的主体：字号最大、字重加粗、可换行完整显示。 */
.skill-name {
  grid-column: 1;
  min-width: 0;
  padding: 2px 4px;
  border: 1px solid transparent;
  border-radius: var(--ja-radius);
  background: none;
  color: var(--ja-color-text);
  font-size: 16px;
  font-weight: 650;
  line-height: 1.5;
  text-align: left;
  overflow-wrap: anywhere;
  cursor: text;
}
.skill-name:hover { border-color: var(--ja-color-border); background: var(--ja-color-primary-soft); }
/* 删除按钮：图标按钮，与技能名同一行、靠上对齐。 */
.skill-remove { grid-column: 2; grid-row: 1; }
/* 编辑态保持与只读态同样的字号，避免进入编辑时卡片高度跳动。 */
.skill-card :deep(.ant-input) { font-size: 16px; font-weight: 650; }
/* 原文出处下移到第三行区域，字号更小、颜色更弱，完整内容通过 title 查看。 */
.skill-quote {
  grid-column: 1 / -1;
  margin-top: 10px;
  min-width: 0;
  color: var(--ja-color-muted);
  font-size: 11px;
  line-height: 1.6;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 640px) {
  .skill-grid { grid-template-columns: minmax(0, 1fr); }
}
.candidate-section h3 { margin-bottom: 10px; font-size: 15px; }
.candidate-item { margin-bottom: 10px; }
.candidate-item :deep(.ant-card-head) { min-height: 42px; }
.candidate-item :deep(.ant-form-item) { margin-bottom: 8px; }
.full-width { width: 100%; }
.source-quote { margin: 6px 0 0; color: var(--ja-color-muted); font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.import-diagnostics { margin: 8px 0 0; padding-left: 20px; }
</style>
