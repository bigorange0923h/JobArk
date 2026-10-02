<script setup lang="ts">
/**
 * 招聘平台内容导入：先预览，再由用户核对后确认写入。
 *
 * 原始页面内容仅作为请求输入，不执行 HTML。编辑输入会使旧预览不可确认；取消和失败保留草稿。
 * 已存在的平台页面只允许核对 JD，元数据使用服务端提供的现有值，避免覆盖人工维护的事实。
 */

import { computed, ref } from 'vue'

import { ApiError } from '@/shared/api/client'
import {
  confirmJobImport,
  previewJobImport,
  type JobImportCandidate,
  type JobImportFields,
  type JobImportPreviewInput,
  type JobImportSource,
} from '@/shared/api/jobImport'
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { createLocalError, type ParsedServerError } from '@/shared/forms/serverErrors'

const emit = defineEmits<{
  /** 已确认写入，父列表应重新读取职位。 */
  saved: []
}>()

const MAX_HTML_FILE_BYTES = 1024 * 1024
const sourceLabels: Record<JobImportSource, string> = {
  LINKEDIN: '领英', INDEED: 'Indeed', BOSS: 'BOSS 直聘', FIFTYONEJOB: '51job',
}
const open = ref(false)
const input = ref<JobImportPreviewInput>({ url: '', mode: 'TEXT', content: '' })
const candidate = ref<JobImportCandidate | null>(null)
const draft = ref<JobImportFields | null>(null)
/** 预览时的原输入单独保存，防止编辑输入后误确认旧页面。 */
const previewInput = ref<JobImportPreviewInput | null>(null)
const previewLoading = ref(false)
const confirmLoading = ref(false)
const fileLoading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const error = ref<ParsedServerError | null>(null)
/** 409 后保留草稿，但必须重新获取目标版本后才允许确认。 */
const needsPreview = ref(false)
const result = ref('')

const busy = computed(() => previewLoading.value || confirmLoading.value || fileLoading.value)
const inputChanged = computed(() => previewInput.value !== null && (
  input.value.url.trim() !== previewInput.value.url
  || input.value.mode !== previewInput.value.mode
  || input.value.content !== previewInput.value.content
))
const updating = computed(() => candidate.value?.target_posting_id != null)
const canPreview = computed(() => !busy.value && !!input.value.url.trim() && !!input.value.content.trim())
const canConfirm = computed(() => !busy.value && !inputChanged.value && !needsPreview.value
  && candidate.value?.status === 'PENDING' && draft.value !== null
  && !!draft.value.company_name.trim() && !!draft.value.title.trim() && !!draft.value.raw_jd.trim())
const errorDescription = computed(() => {
  if (error.value === null) return undefined
  const parts = [...error.value.general]
  if (error.value.requestId) parts.push(`错误编号：${error.value.requestId}`)
  return parts.join(' ') || undefined
})

/** 打开与取消都不清除输入，用户可继续修改尚未确认的候选。 */
function togglePanel(): void {
  if (busy.value) return
  open.value = !open.value
}

/** 只读本地文件正文；失败和取消选择均保留原有输入，不解析或执行 HTML。 */
async function onFileChange(event: Event): Promise<void> {
  if (busy.value) return
  const target = event.target as HTMLInputElement
  const selected = target.files?.[0]
  target.value = ''
  if (!selected) return
  if (!/\.(html|htm)$/i.test(selected.name) || selected.size === 0 || selected.size > MAX_HTML_FILE_BYTES) {
    error.value = createLocalError('请选择不超过 1 MB 的 HTML 文件。')
    return
  }
  fileLoading.value = true
  error.value = null
  try {
    const content = await readTextFile(selected)
    input.value.mode = 'HTML'
    input.value.content = content
  } catch {
    error.value = createLocalError('无法读取 HTML 文件，请重新选择或粘贴页面内容。')
  } finally {
    fileLoading.value = false
  }
}

/** FileReader 只读取文本，不创建可执行页面；兼容现有浏览器和组件测试环境。 */
function readTextFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('文件读取失败。'))
    reader.onerror = () => reject(new Error('文件读取失败。'))
    reader.readAsText(file)
  })
}

/** 获取候选并复制可编辑字段；这里绝不调用正式确认接口。 */
async function preview(): Promise<void> {
  if (!canPreview.value) return
  const payload = { ...input.value, url: input.value.url.trim() }
  previewLoading.value = true
  error.value = null
  result.value = ''
  try {
    const next = await previewJobImport(payload)
    candidate.value = next
    draft.value = { ...next.fields }
    previewInput.value = payload
    needsPreview.value = false
  } catch (failure: unknown) {
    error.value = resolveActionFailure(failure, '预览职位内容')
  } finally {
    previewLoading.value = false
  }
}

/** 仅用户点击确认才写入；已有页面的元数据始终从原候选取值，不能由草稿覆盖。 */
async function confirm(): Promise<void> {
  if (!canConfirm.value || candidate.value === null || draft.value === null) return
  const original = candidate.value
  const fields = updating.value ? { ...original.fields, raw_jd: draft.value.raw_jd } : {
    ...draft.value,
    company_name: draft.value.company_name.trim(),
    title: draft.value.title.trim(),
    location: draft.value.location?.trim() || null,
  }
  confirmLoading.value = true
  error.value = null
  try {
    await confirmJobImport(original.id, { version: original.version, confirm: true, fields })
    result.value = updating.value ? '已确认更新 JD，历史快照已保留。' : '已确认导入职位与 JD。'
    input.value = { url: '', mode: 'TEXT', content: '' }
    candidate.value = null
    draft.value = null
    previewInput.value = null
    needsPreview.value = false
    open.value = false
    emit('saved')
  } catch (failure: unknown) {
    error.value = resolveActionFailure(failure, '确认导入职位')
    // 过期、版本变化等冲突不能反复提交旧候选；草稿留下供用户核对重新预览。
    if (failure instanceof ApiError && failure.status === 409) {
      needsPreview.value = true
    }
  } finally {
    confirmLoading.value = false
  }
}
</script>

<template>
  <a-card size="small" title="从招聘平台导入" class="job-import-panel">
    <p class="import-description">
      支持领英、Indeed、BOSS 直聘、51job 的单个职位详情链接。请提供你已获得的正文或 HTML；当前支持内容导入，不会自动访问网站。
    </p>
    <a-button :disabled="busy" data-testid="open-job-import" @click="togglePanel">
      {{ open ? '收起导入' : '导入职位内容' }}
    </a-button>
    <p v-if="result" role="status" class="import-result" data-testid="job-import-result">
      {{ result }}
    </p>

    <div v-if="open" class="import-content" data-testid="job-import-content">
      <a-alert
        v-if="error"
        type="error"
        show-icon
        :message="error.message"
        :description="errorDescription"
        class="import-error"
        data-testid="job-import-error"
      />
      <h3>1. 提供页面内容</h3>
      <a-form layout="vertical" @submit.prevent="preview">
        <a-form-item
          label="职位详情 URL"
          required
          :validate-status="error?.fields.url ? 'error' : undefined"
          :help="error?.fields.url"
          extra="请使用单个职位详情链接；不接受职位列表、搜索或登录页面。"
        >
          <a-input
            v-model:value="input.url"
            :disabled="busy"
            :maxlength="2048"
            placeholder="https://…"
            data-testid="job-import-url"
          />
        </a-form-item>
        <a-form-item label="内容格式">
          <a-radio-group v-model:value="input.mode" :disabled="busy" data-testid="job-import-mode">
            <a-radio-button value="TEXT">可见正文</a-radio-button>
            <a-radio-button value="HTML">HTML</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <a-form-item
          :label="input.mode === 'HTML' ? '页面 HTML' : '页面正文'"
          required
          :validate-status="error?.fields.content ? 'error' : undefined"
          :help="error?.fields.content"
          extra="只提供职位内容，请勿粘贴 Cookie、登录凭据或浏览器会话信息。内容不会发送给 AI。"
        >
          <a-textarea
            v-model:value="input.content"
            :disabled="busy"
            :rows="6"
            data-testid="job-import-source-content"
          />
        </a-form-item>
        <input
          ref="fileInput"
          type="file"
          accept=".html,.htm,text/html"
          hidden
          data-testid="job-import-file"
          @change="onFileChange"
        />
        <div class="import-actions">
          <a-button
            :disabled="busy"
            :loading="fileLoading"
            data-testid="read-job-import-file"
            @click="fileInput?.click()"
          >
            读取本地 HTML（最多 1 MB）
          </a-button>
          <a-button
            type="primary"
            :disabled="!canPreview"
            :loading="previewLoading"
            data-testid="preview-job-import"
            @click="preview"
          >
            {{ candidate ? '重新预览' : '预览内容' }}
          </a-button>
        </div>
      </a-form>

      <div v-if="candidate && draft" class="import-review" data-testid="job-import-review">
        <h3>2. 核对并确认</h3>
        <p>
          <a-tag>{{ sourceLabels[candidate.source] }}</a-tag>
          <a-tag :color="updating ? 'blue' : 'green'">
            {{ updating ? '更新已有页面的 JD' : '新建职位' }}
          </a-tag>
        </p>
        <p class="import-source">来源：{{ candidate.canonical_url }}</p>
        <p>有效期至 {{ new Date(candidate.expires_at).toLocaleString('zh-CN', { hour12: false }) }}。确认前请核对正文与原页面。</p>
        <a-alert
          v-if="inputChanged || needsPreview"
          type="warning"
          show-icon
          message="请重新预览后再确认。"
          :description="inputChanged ? '页面链接、格式或内容已变化，当前候选对应旧输入。' : '候选已过期或页面版本发生变化，现有输入和核对草稿已保留。'"
          class="import-warning"
          data-testid="job-import-repreview"
        />
        <a-alert
          v-if="candidate.warnings.length"
          type="warning"
          show-icon
          message="请核对提取结果"
          class="import-warning"
          data-testid="job-import-warnings"
        >
          <template #description>
            <ul>
              <li v-for="(warning, index) in candidate.warnings" :key="index">
                {{ warning }}
              </li>
            </ul>
          </template>
        </a-alert>
        <p v-if="updating" data-testid="job-import-existing-notice">
          此页面已有职位。公司、职位与地点保留已保存值，本次只更新 JD。
        </p>
        <p v-else>
          公司、职位、地点与 JD 都是待核对内容；缺失字段由你补充，不代表平台事实已核实。
        </p>
        <a-form layout="vertical" @submit.prevent="confirm">
          <div class="review-grid">
            <a-form-item
              label="公司"
              required
              :validate-status="error?.fields['fields.company_name'] ? 'error' : undefined"
              :help="error?.fields['fields.company_name']"
            >
              <a-input
                v-model:value="draft.company_name"
                :disabled="busy || updating"
                :maxlength="200"
                data-testid="job-import-company"
              />
            </a-form-item>
            <a-form-item
              label="职位"
              required
              :validate-status="error?.fields['fields.title'] ? 'error' : undefined"
              :help="error?.fields['fields.title']"
            >
              <a-input
                v-model:value="draft.title"
                :disabled="busy || updating"
                :maxlength="200"
                data-testid="job-import-title"
              />
            </a-form-item>
            <a-form-item label="地点">
              <a-input
                v-model:value="draft.location"
                :disabled="busy || updating"
                :maxlength="200"
                data-testid="job-import-location"
              />
            </a-form-item>
          </div>
          <a-form-item
            label="JD 正文"
            required
            :validate-status="error?.fields['fields.raw_jd'] ? 'error' : undefined"
            :help="error?.fields['fields.raw_jd']"
          >
            <a-textarea
              v-model:value="draft.raw_jd"
              :disabled="busy"
              :rows="8"
              :maxlength="100000"
              data-testid="job-import-jd"
            />
          </a-form-item>
          <p>点击下方确认会保存职位信息与 JD；预览和取消不会写入正式职位。</p>
          <a-button
            type="primary"
            :disabled="!canConfirm"
            :loading="confirmLoading"
            data-testid="confirm-job-import"
            @click="confirm"
          >
            {{ updating ? '确认更新 JD' : '确认导入职位与 JD' }}
          </a-button>
        </a-form>
      </div>
      <a-button
        :disabled="busy"
        class="cancel-import"
        data-testid="cancel-job-import"
        @click="togglePanel"
      >
        取消，保留输入
      </a-button>
    </div>
  </a-card>
</template>

<style scoped>
.job-import-panel { margin: 1rem 0; }
.import-description, .import-source { overflow-wrap: anywhere; }
.import-content, .import-review { margin-top: 1rem; }
.import-review { border-top: 1px solid var(--ja-border, #e5e7eb); padding-top: 1rem; }
.import-error, .import-warning { margin-bottom: 1rem; }
.import-actions { display: flex; flex-wrap: wrap; gap: .75rem; }
.review-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 0 1rem; }
.cancel-import { margin-top: 1rem; }
.import-result { margin-top: .75rem; }
</style>
