<script setup lang="ts">
/**
 * 手工职位录入与列表页。
 *
 * 这页只负责收集和展示，不在浏览器解析 JD 或推断匹配结论；`NOT_REQUESTED` 是诚实的状态，
 * 等受控解析器及其失败语义实现后再增加分析入口。
 */

import { computed, onMounted, ref } from 'vue'

import { createManualJob, listJobs, previewExclusion, type ExclusionEvaluation, type JobListItem, type ManualJobCreate } from '@/shared/api/job'
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import JobImportPanel from './JobImportPanel.vue'

const jobs = ref<JobListItem[]>([])
const filter = ref<'ALL' | 'ELIGIBLE' | 'REVIEW' | 'EXCLUDED'>('ALL')
const evaluations = ref<Record<string, ExclusionEvaluation | null>>({})
const evaluationErrors = ref<Record<string, string>>({})
const visibleJobs = computed(() => jobs.value.filter(job => filter.value === 'ALL' || (evaluations.value[job.id]?.decision.verdict ?? 'REVIEW') === filter.value))
const loading = ref(false)
const submitting = ref(false)
/** 页面初始加载失败：保留页面内提示与重试入口。 */
const loadError = ref<ParsedServerError | null>(null)
/** 保存失败：字段级原因内联展示，网络与超时等无字段信息的原因走全局通知。 */
const actionError = ref<ParsedServerError | null>(null)
const form = ref<ManualJobCreate>(emptyForm())
const employmentTypeOptions = computed(() => [
  ...new Set(['全职', '兼职', '实习', '合同制', ...jobs.value.map((job) => job.employment_type).filter((value): value is string => !!value)]),
].map((value) => ({ value, label: value })))

const columns = [
  { key: 'company_name', title: '公司', dataIndex: 'company_name' },
  { key: 'title', title: '职位', dataIndex: 'title' },
  { key: 'location', title: '地点', dataIndex: 'location' },
  { key: 'employment_type', title: '类型', dataIndex: 'employment_type' },
  { key: 'status', title: '状态', dataIndex: 'status' },
  { key: 'exclusion', title: '策略判定' },
  { key: 'latest_captured_at', title: '最近 JD', dataIndex: 'latest_captured_at' },
]

const errorDescription = computed(() => {
  if (loadError.value === null) return undefined
  const content = [...loadError.value.general]
  if (loadError.value.requestId) content.push(`错误编号：${loadError.value.requestId}`)
  return content.join(' ') || undefined
})

const actionErrorDescription = computed(() => {
  if (actionError.value === null) return undefined
  const content = [...actionError.value.general]
  if (actionError.value.requestId) content.push(`错误编号：${actionError.value.requestId}`)
  return content.join(' ') || undefined
})

function emptyForm(): ManualJobCreate {
  return {
    company: { name: '', website_url: null, industry: null, location: null },
    title: '',
    location: null,
    employment_type: null,
    notes: null,
    canonical_url: null,
    raw_jd: '',
  }
}

function blankToNull(value: string | null): string | null {
  const trimmed = value?.trim() ?? ''
  return trimmed === '' ? null : trimmed
}

function payload(): ManualJobCreate {
  return {
    ...form.value,
    company: {
      ...form.value.company,
      name: form.value.company.name.trim(),
      website_url: blankToNull(form.value.company.website_url),
      industry: blankToNull(form.value.company.industry),
      location: blankToNull(form.value.company.location),
    },
    title: form.value.title.trim(),
    location: blankToNull(form.value.location),
    employment_type: blankToNull(form.value.employment_type),
    notes: blankToNull(form.value.notes),
    canonical_url: blankToNull(form.value.canonical_url),
    raw_jd: form.value.raw_jd,
  }
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    jobs.value = await listJobs()
    const outcomes = await Promise.allSettled(jobs.value.map(job => previewExclusion(job.id)))
    evaluations.value = {}; evaluationErrors.value = {}
    outcomes.forEach((outcome, index) => {
      const id = jobs.value[index]!.id
      if (outcome.status === 'fulfilled') evaluations.value[id] = outcome.value
      else { evaluations.value[id] = null; evaluationErrors.value[id] = parseServerError(outcome.reason).message }
    })
  } catch (error: unknown) {
    loadError.value = parseServerError(error)
  } finally {
    loading.value = false
  }
}

async function submit(): Promise<void> {
  const input = payload()
  if (input.company.name === '' || input.title === '' || !input.raw_jd.trim()) return
  submitting.value = true
  actionError.value = null
  try {
    await createManualJob(input)
    form.value = emptyForm()
    await load()
  } catch (error: unknown) {
    // 422 字段错误与冲突留在表单上方；网络、超时与服务端错误走全局通知，不再插入页面内错误块。
    actionError.value = resolveActionFailure(error, '保存职位')
  } finally {
    submitting.value = false
  }
}

function statusLabel(status: string): string {
  return status === 'ARCHIVED' ? '已归档' : '处理中'
}

function formatTime(value: string | null): string {
  return value === null ? '—' : new Date(value).toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => void load())
</script>

<template>
  <section class="job-list-view">
    <header class="page-header">
      <div><p class="page-eyebrow">JOBS</p><h1>职位</h1><p class="page-subtitle">保存原始 JD，按机会持续跟进。</p></div>
      <a-button size="small" :loading="loading" data-testid="reload" @click="load">刷新</a-button>
    </header>

    <JobImportPanel @saved="load" />

    <a-alert
      v-if="actionError"
      type="error"
      show-icon
      closable
      :message="actionError.message"
      :description="actionErrorDescription"
      class="action-error"
      data-testid="form-error"
      @close="actionError = null"
    />

    <a-card size="small" title="手工录入职位">
      <a-form layout="vertical" @submit.prevent="submit">
        <div class="form-grid">
          <a-form-item label="公司" required><a-input v-model:value="form.company.name" :maxlength="200" data-testid="company-name" /></a-form-item>
          <a-form-item label="职位" required><a-input v-model:value="form.title" :maxlength="200" data-testid="job-title" /></a-form-item>
          <a-form-item label="职位地点"><a-input v-model:value="form.location" :maxlength="200" /></a-form-item>
          <a-form-item label="雇佣类型" extra="优先选择常见类型；列表外的类型可直接输入。"><a-auto-complete v-model:value="form.employment_type" :options="employmentTypeOptions" :maxlength="80" placeholder="选择或输入雇佣类型" data-testid="job-employment-type" /></a-form-item>
          <a-form-item label="招聘页面 URL"><a-input v-model:value="form.canonical_url" :maxlength="2048" /></a-form-item>
          <a-form-item label="公司官网"><a-input v-model:value="form.company.website_url" :maxlength="2048" /></a-form-item>
        </div>
        <a-form-item label="JD 原文" required><a-textarea v-model:value="form.raw_jd" :rows="7" :maxlength="100000" data-testid="raw-jd" /></a-form-item>
        <a-form-item label="个人备注"><a-textarea v-model:value="form.notes" :rows="2" :maxlength="10000" /></a-form-item>
        <a-button type="primary" :loading="submitting" :disabled="!form.company.name.trim() || !form.title.trim() || !form.raw_jd.trim()" data-testid="create-job" @click="submit">保存职位与 JD</a-button>
      </a-form>
    </a-card>

    <a-alert v-if="loadError" type="error" show-icon :message="loadError.message" :description="errorDescription" class="load-error" data-testid="load-error" />
    <a-radio-group v-model:value="filter" class="job-filters">
      <a-radio-button value="ALL">全部</a-radio-button><a-radio-button value="ELIGIBLE">可考虑</a-radio-button>
      <a-radio-button value="REVIEW">待核对</a-radio-button><a-radio-button value="EXCLUDED">已排除</a-radio-button>
    </a-radio-group>
    <a-table v-if="!loadError" :columns="columns" :data-source="visibleJobs" :loading="loading" :pagination="false" row-key="id" class="job-table">
      <template #bodyCell="{ column, record }">
        <RouterLink v-if="column.key === 'title'" :to="`/jobs/${record.id}`">{{ record.title }}</RouterLink>
        <template v-else-if="column.key === 'status'">{{ statusLabel(record.status) }}</template>
        <template v-else-if="column.key === 'exclusion'">
          <a-tag :color="evaluations[record.id]?.decision.verdict === 'EXCLUDED' ? 'red' : evaluations[record.id]?.decision.verdict === 'ELIGIBLE' ? 'green' : 'orange'">
            {{ evaluations[record.id]?.decision.verdict === 'EXCLUDED' ? '已排除' : evaluations[record.id]?.decision.verdict === 'ELIGIBLE' ? '可考虑' : '待核对' }}
          </a-tag>
          <div v-if="evaluationErrors[record.id]">评估失败：{{ evaluationErrors[record.id] }}</div>
          <div v-for="(reason, index) in evaluations[record.id]?.decision.reasons ?? []" :key="index">{{ reason.text }}<span v-if="reason.snippet">：{{ reason.snippet }}</span></div>
        </template>
        <template v-else-if="column.key === 'latest_captured_at'">{{ formatTime(record.latest_captured_at) }}</template>
        <template v-else>{{ record[column.dataIndex] ?? '—' }}</template>
      </template>
    </a-table>
  </section>
</template>

<style scoped>
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: 0 1rem; }
.action-error, .load-error, .job-table { margin-top: 1rem; }
.job-filters { margin-top: 1rem; }
</style>
