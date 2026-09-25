<script setup lang="ts">
/**
 * 文档导入只保留临时候选；确认前不把 AI 结果写入档案。
 *
 * 候选在预览阶段可编辑：用户修正或补全的字段可能不再逐字出现在原文摘录中，后端会把这类条目
 * 改挂"本人陈述"证据；因此这里让除 `source_quote` 之外的字段可改，而摘录保持只读——它是来源凭证，
 * 允许编辑就等于允许伪造来源。
 *
 * 各分区的字段配置集中在本文件的 `SECTIONS` 里，与后端候选结构一一对应；
 * 新增一类候选只需要在这里加一个分区，而不是再写一段结构相同的模板。
 */
import { computed, ref } from 'vue'

import {
  confirmProfileImport,
  previewProfileImportStream,
  type ProfileImportCandidate,
  type ProfileImportPreview,
  type ProfileImportStage,
} from '@/shared/api/profile'
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { createLocalError, type ParsedServerError } from '@/shared/forms/serverErrors'

defineProps<{ hasProfile: boolean }>()
const emit = defineEmits<{ changed: [] }>()

type CandidateSectionKey = 'skills' | 'experiences' | 'projects' | 'educations'
type CandidateFieldKind = 'text' | 'textarea' | 'date' | 'tags'
/** 候选条目在界面上按普通字典读写：字段名与后端契约一致，逐字段收窄只在取值处做。 */
type CandidateItem = Record<string, unknown>

interface CandidateField {
  name: string
  label: string
  kind: CandidateFieldKind
}

interface CandidateSection {
  key: CandidateSectionKey
  title: string
  fields: CandidateField[]
  /** 复选框旁的一句话摘要，让用户先看清条目再决定是否展开核对。 */
  summary: (item: CandidateItem) => string
}

const BASIC_FIELDS = [
  { name: 'full_name', label: '姓名' },
  { name: 'headline', label: '头衔' },
  { name: 'email', label: '邮箱' },
  { name: 'phone', label: '手机' },
  { name: 'city', label: '城市' },
] as const

const SECTIONS: CandidateSection[] = [
  {
    key: 'skills',
    title: '技能',
    fields: [{ name: 'name', label: '技能名称', kind: 'text' }],
    summary: (item) => String(item['name'] ?? ''),
  },
  {
    key: 'experiences',
    title: '工作经历',
    fields: [
      { name: 'company', label: '公司', kind: 'text' },
      { name: 'title', label: '职位', kind: 'text' },
      { name: 'location', label: '地点', kind: 'text' },
      { name: 'start_date', label: '开始日期', kind: 'date' },
      { name: 'end_date', label: '结束日期', kind: 'date' },
      { name: 'responsibilities', label: '职责', kind: 'textarea' },
      { name: 'achievements', label: '成果', kind: 'textarea' },
    ],
    summary: (item) =>
      `${item['company'] ?? ''} · ${item['title'] ?? ''}（${item['start_date'] ?? ''} — ${item['end_date'] ?? '至今'}）`,
  },
  {
    key: 'projects',
    title: '项目经历',
    fields: [
      { name: 'name', label: '项目名称', kind: 'text' },
      { name: 'role', label: '本人角色', kind: 'text' },
      { name: 'description', label: '项目说明', kind: 'textarea' },
      { name: 'responsibilities', label: '职责', kind: 'textarea' },
      { name: 'achievements', label: '成果', kind: 'textarea' },
      { name: 'tech_stack', label: '技术栈', kind: 'tags' },
      { name: 'url', label: '项目链接', kind: 'text' },
      { name: 'start_date', label: '开始日期', kind: 'date' },
      { name: 'end_date', label: '结束日期', kind: 'date' },
    ],
    summary: (item) => String(item['name'] ?? ''),
  },
  {
    key: 'educations',
    title: '教育经历',
    fields: [
      { name: 'school', label: '学校', kind: 'text' },
      { name: 'major', label: '专业', kind: 'text' },
      { name: 'degree', label: '学历/学位', kind: 'text' },
      { name: 'start_date', label: '开始日期', kind: 'date' },
      { name: 'end_date', label: '结束日期', kind: 'date' },
    ],
    summary: (item) =>
      `${item['school'] ?? ''} · ${item['major'] ?? '专业未提供'} · ${item['degree'] ?? '学历未提供'}`,
  },
]

const fileInput = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const contentBase64 = ref('')
/** 服务端返回的预览（原文件哈希等），写入时仍以它为准做换文件校验。 */
const preview = ref<ProfileImportPreview | null>(null)
/** 用户可编辑的候选副本；与 `preview.candidate` 分离，避免改动污染原始预览。 */
const draft = ref<ProfileImportCandidate | null>(null)
const consent = ref(false)
const reviewed = ref(false)
const busyPreview = ref(false)
const progressStage = ref<ProfileImportStage | 'reading_file'>('reading_file')
const busyConfirm = ref(false)
/** 本地文件校验与服务端失败共用一个提示位置；无法定位字段的失败走全局通知。 */
const error = ref<ParsedServerError | null>(null)
const result = ref('')
const selected = ref<Record<CandidateSectionKey, number[]>>({
  skills: [],
  experiences: [],
  projects: [],
  educations: [],
})
const busy = computed(() => busyPreview.value || busyConfirm.value)
const progressText = computed(() => ({
  reading_file: '正在读取文件…',
  received: '请求已送达，正在解析文档…',
  document_parsed: '文档解析完成，正在读取模型配置…',
  model_resolved: '模型配置已读取，准备生成候选…',
  ai_request_started: '模型正在生成候选，通常需要几十秒…',
  ai_request_retrying: '模型服务短暂不可用，正在自动重试一次…',
  ai_response_parsed: '模型已返回，正在校验候选结构和原文摘录…',
  candidate_validated: '候选已校验，正在展示预览…',
})[progressStage.value])

/** 局部候选必须明确说明遗漏，不能让用户把可确认条目误认为整份简历已被完整抽取。 */
const partialPreviewMessage = computed(() => {
  const current = preview.value
  if (current === null || current.completeness.status !== 'PARTIAL') return ''
  const { valid_item_count, rejected_item_count, unmapped_field_count } = current.completeness
  const parts = [`本次仅生成部分可验证候选：${valid_item_count} 条可核对`]
  if (rejected_item_count > 0) parts.push(`${rejected_item_count} 条因格式或证据不足未纳入`)
  if (unmapped_field_count > 0) parts.push(`${unmapped_field_count} 个未映射字段未导入`)
  return `${parts.join('，')}。请检查下方遗漏说明或手工补录。`
})

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

function chooseFile(): void {
  fileInput.value?.click()
}

/** 换文件即清除旧候选，避免把上一份简历的选择应用到新文件。 */
function onFileChange(event: Event): void {
  const target = event.target as HTMLInputElement
  const next = target.files?.[0] ?? null
  target.value = ''
  file.value = null
  contentBase64.value = ''
  preview.value = null
  draft.value = null
  reviewed.value = false
  consent.value = false
  result.value = ''
  error.value = null
  if (!next) return
  if (!/\.(pdf|html|htm)$/i.test(next.name) || next.size === 0 || next.size > 3 * 1024 * 1024) {
    error.value = createLocalError('请选择不超过 3 MB 的 PDF 或 HTML 简历文件。')
    return
  }
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

/** 只在明确勾选外部发送确认后生成预览。 */
async function generate(): Promise<void> {
  if (!file.value || !consent.value || busy.value) return
  busyPreview.value = true
  progressStage.value = 'reading_file'
  error.value = null
  result.value = ''
  preview.value = null
  draft.value = null
  try {
    contentBase64.value = await encodeFile(file.value)
    const next = await previewProfileImportStream(file.value.name, contentBase64.value, consent.value, (stage) => {
      progressStage.value = stage
    })
    preview.value = next
    draft.value = cloneCandidate(next.candidate)
    selected.value = {
      skills: next.candidate.skills.map((_, index) => index),
      experiences: next.candidate.experiences.map((_, index) => index),
      projects: next.candidate.projects.map((_, index) => index),
      educations: next.candidate.educations.map((_, index) => index),
    }
    reviewed.value = false
  } catch (cause: unknown) {
    // 文件读取失败是本地问题，需要就地提示；服务端失败中无法定位字段的走全局通知。
    error.value = cause instanceof Error && cause.message === '文件读取失败。'
      ? createLocalError(cause.message) : resolveActionFailure(cause, '生成导入候选')
  } finally {
    busyPreview.value = false
  }
}

function toggle(key: CandidateSectionKey, index: number, checked: boolean): void {
  const current = selected.value[key]
  selected.value[key] = checked ? [...current, index] : current.filter((value) => value !== index)
  reviewed.value = false
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

function basicTextOf(name: (typeof BASIC_FIELDS)[number]['name']): string {
  const candidate = draft.value
  if (candidate === null) return ''
  const value: unknown = candidate[name]
  return typeof value === 'string' ? value : ''
}

/** 写入一个候选字段；空字符串视为清空，与后端"缺失字段留空"的语义一致。 */
function setValue(key: CandidateSectionKey, index: number, field: CandidateField, value: unknown): void {
  const candidate = draft.value
  if (candidate === null) return
  const item = (candidate[key] as unknown as CandidateItem[])[index]
  if (item === undefined) return
  if (field.kind === 'tags') {
    item[field.name] = Array.isArray(value) ? value : []
  } else {
    const text = typeof value === 'string' ? value : ''
    item[field.name] = text === '' ? null : text
  }
  reviewed.value = false
}

function setBasic(name: (typeof BASIC_FIELDS)[number]['name'], value: unknown): void {
  const candidate = draft.value
  if (candidate === null) return
  const text = typeof value === 'string' ? value : ''
  if (name === 'full_name') {
    candidate.full_name = text
  } else {
    candidate[name] = text === '' ? null : text
  }
  reviewed.value = false
}

/** 用户确认后一次性提交；已有基本资料绝不从候选覆盖。 */
async function apply(): Promise<void> {
  if (preview.value === null || draft.value === null || file.value === null || !reviewed.value || busy.value) return
  busyConfirm.value = true
  error.value = null
  try {
    const saved = await confirmProfileImport({
      filename: file.value.name,
      contentBase64: contentBase64.value,
      sourceHash: preview.value.source_hash,
      candidate: draft.value,
      skillIndices: selected.value.skills,
      experienceIndices: selected.value.experiences,
      projectIndices: selected.value.projects,
      educationIndices: selected.value.educations,
    })
    result.value =
      `已${saved.created_profile ? '创建档案并' : ''}导入 ${saved.experiences_added} 段工作经历、`
      + `${saved.projects_added} 个项目经历、${saved.educations_added} 段教育经历和 ${saved.skills_added} 项技能，`
      + '均为“未验证”状态；可在下方各面板中继续编辑。'
    preview.value = null
    draft.value = null
    file.value = null
    contentBase64.value = ''
    reviewed.value = false
    consent.value = false
    emit('changed')
  } catch (cause: unknown) {
    error.value = resolveActionFailure(cause, '导入简历候选')
  } finally {
    busyConfirm.value = false
  }
}
</script>

<template>
  <a-card title="从已有简历导入" class="import-panel" data-testid="profile-import-panel">
    <p class="import-intro">上传带文字层的 PDF 或 HTML 简历，先预览候选，再选择要写入的内容。原文件不会保存在服务端；扫描件暂不支持 OCR。短暂的模型连接或服务错误会最多自动重试一次。</p>
    <a-alert v-if="hasProfile" type="info" show-icon message="已有档案只补充经历与技能，不覆盖现有基本信息。" class="import-notice" />
    <div class="file-row">
      <input ref="fileInput" class="file-input" type="file" accept=".pdf,.html,.htm,application/pdf,text/html" aria-label="选择 PDF 或 HTML 简历" @change="onFileChange" />
      <a-button :disabled="busy" data-testid="choose-resume-file" @click="chooseFile">选择简历文件</a-button>
      <span class="file-name">{{ file?.name ?? '尚未选择文件' }}</span>
    </div>
    <a-checkbox v-model:checked="consent" :disabled="!file || busy" data-testid="profile-import-consent">
      我同意将简历提取文字（可能包含姓名、联系方式和工作经历）发送到已配置的 AI 网关；短暂失败时最多会再发送一次
    </a-checkbox>
    <div class="import-actions">
      <a-button type="primary" :loading="busyPreview" :disabled="!file || !consent || busy" data-testid="preview-import" @click="generate">生成待核对候选</a-button>
    </div>
    <div v-if="busyPreview" class="import-progress" role="status" aria-live="polite" data-testid="profile-import-progress">
      <a-spin size="small" />
      <span>{{ progressText }}</span>
    </div>
    <a-alert v-if="error" type="error" show-icon :message="error.message" :description="errorDescription" class="import-notice" data-testid="profile-import-error" />
    <a-alert v-if="result" type="success" show-icon :message="result" class="import-notice" data-testid="profile-import-success" />

    <div v-if="draft" class="candidate" data-testid="profile-import-preview">
      <a-divider>待核对内容</a-divider>
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
              {{ item.group }} 第 {{ item.index + 1 }} 条：{{ item.message }}
            </li>
            <li v-for="warning in preview?.warnings" :key="`warning-${warning.group}-${warning.index}`">
              {{ warning.group }} 第 {{ warning.index + 1 }} 条：{{ warning.fields.join('、') }} 未映射，未作为事实导入。
            </li>
          </ul>
        </template>
      </a-alert>
      <p class="candidate-note">
        以下均是未验证候选，可直接修正或补全字段；摘录只读，它记录内容在原文中的出处。
        取消勾选可排除错误条目。简历只写年份或年月时，日期中的缺失月份/日可能以 1 补位，不表示原文提供了精确日期。
        修正过的条目写入后会以“本人陈述”作为来源，而不是简历原文。
      </p>
      <a-form layout="vertical" class="basics-form">
        <a-form-item v-for="field in BASIC_FIELDS" :key="field.name" :label="field.label">
          <a-input
            :value="basicTextOf(field.name)"
            allow-clear
            :data-testid="`candidate-basics-${field.name}`"
            @update:value="(value: unknown) => setBasic(field.name, value)"
          />
        </a-form-item>
      </a-form>
      <p class="source-quote">姓名原文：{{ draft.name_quote }}</p>

      <section v-for="section in SECTIONS" :key="section.key" class="candidate-section">
        <h3>{{ section.title }}（{{ itemsOf(section.key).length }}）</h3>
        <a-empty v-if="!itemsOf(section.key).length" :description="`未提取到${section.title}`" />
        <div
          v-for="(item, index) in itemsOf(section.key)"
          :key="index"
          class="candidate-item"
          :data-testid="`candidate-item-${section.key}-${index}`"
        >
          <a-checkbox
            :checked="selected[section.key].includes(index)"
            @update:checked="(checked: boolean) => toggle(section.key, index, checked)"
          >
            {{ section.summary(item) }}
          </a-checkbox>
          <a-form layout="vertical" class="candidate-form">
            <a-form-item v-for="field in section.fields" :key="field.name" :label="field.label">
              <a-input
                v-if="field.kind === 'text'"
                :value="textOf(item, field.name)"
                allow-clear
                @update:value="(value: unknown) => setValue(section.key, index, field, value)"
              />
              <a-textarea
                v-else-if="field.kind === 'textarea'"
                :value="textOf(item, field.name)"
                :rows="2"
                allow-clear
                @update:value="(value: unknown) => setValue(section.key, index, field, value)"
              />
              <a-date-picker
                v-else-if="field.kind === 'date'"
                :value="textOf(item, field.name)"
                value-format="YYYY-MM-DD"
                class="full-width"
                allow-clear
                @update:value="(value: unknown) => setValue(section.key, index, field, value)"
              />
              <a-select
                v-else-if="field.kind === 'tags'"
                :value="tagsOf(item, field.name)"
                mode="tags"
                :token-separators="[',']"
                @update:value="(value: unknown) => setValue(section.key, index, field, value)"
              />
            </a-form-item>
          </a-form>
          <p class="source-quote">原文：{{ textOf(item, 'source_quote') }}</p>
        </div>
      </section>
      <a-checkbox v-model:checked="reviewed" data-testid="profile-import-reviewed">我已对照摘录核对所选内容，理解它们会以“未验证”状态写入档案</a-checkbox>
      <div class="import-actions">
        <a-button type="primary" :loading="busyConfirm" :disabled="!reviewed || busy" data-testid="confirm-import" @click="apply">确认写入个人档案</a-button>
      </div>
    </div>
  </a-card>
</template>

<style scoped>
.import-panel { margin-bottom: var(--ja-space-section); }
.import-intro, .candidate-note { color: var(--ja-color-muted); line-height: 1.65; }
.file-row { display: flex; align-items: center; gap: 12px; margin: 16px 0; flex-wrap: wrap; }
.file-input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.file-name { color: var(--ja-color-muted); font-size: 13px; overflow-wrap: anywhere; }
.import-actions, .import-notice { margin-top: 16px; }
.import-progress { display: flex; align-items: center; gap: 10px; margin-top: 16px; color: var(--ja-color-muted); }
.candidate { margin-top: 20px; }
.basics-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0 12px; }
.basics-form :deep(.ant-form-item) { margin-bottom: 12px; }
.candidate-section { margin: 20px 0; }
.candidate-section h3 { margin-bottom: 10px; font-size: 15px; }
.candidate-item { padding: 10px 12px; border: 1px solid var(--ja-color-border); border-radius: var(--ja-radius); margin-bottom: 8px; }
.candidate-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0 12px; margin-top: 8px; }
.candidate-form :deep(.ant-form-item) { margin-bottom: 8px; }
.full-width { width: 100%; }
.source-quote { margin: 6px 0 0; color: var(--ja-color-muted); font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.import-diagnostics { margin: 8px 0 0; padding-left: 20px; }
</style>
