<script setup lang="ts">
/** 可解释匹配入口：选择不可变输入，逐条阅读证据与未知项。 */
import { computed, onMounted, ref } from 'vue'
import { requestV1 } from '@/shared/api/client'
import { fetchJob, listJobs, listSnapshots, type JobListItem, type JobSnapshot } from '@/shared/api/job'
import { listResumes, listVersions, type ResumeVersion } from '@/shared/api/resume'
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'
interface Report { id: string; created_at: string; match_kind: string; job_snapshot_id: string; profile_revision_id: string; resume_version_id: string | null; report_json: { requirements: { text: string; hard: boolean; status: string; explanation: string; evidence: { fact_id: string; name: string; claim_status: string; evidence_title?: string }[] }[]; uncertainties: string[] } }

/**
 * 命中状态文案。
 *
 * 措辞刻意停在"档案里有这条事实"这一层：命中可能是本人填写、未验证的技能，不能读成能力、
 * 熟练度、年限或整项条件已经核实。`EVIDENCE_FOUND` 是语义调整前写入历史报告的值，按同样意思展示。
 */
const MATCH_STATUS_LABELS: Record<string, string> = {
  FACT_FOUND: '字面匹配：档案中本人填写的事实',
  EVIDENCE_ATTACHED: '字面匹配：该事实另挂来源记录',
  UNKNOWN: '未找到档案事实',
  EVIDENCE_FOUND: '字面匹配',
}

const CLAIM_STATUS_LABELS: Record<string, string> = {
  VERIFIED: '已验证',
  UNVERIFIED: '未验证',
  UNCERTAIN: '待确认',
}

function matchStatusLabel(status: string): string {
  return MATCH_STATUS_LABELS[status] ?? status
}

function claimStatusLabel(status: string): string {
  return CLAIM_STATUS_LABELS[status] ?? status
}

/** 命中事实的来源说明：有来源记录就显示标题，否则如实说明这是本人填写。 */
function evidenceSourceLabel(item: { evidence_title?: string }): string {
  return item.evidence_title ? `来源：${item.evidence_title}` : '本人填写，未挂来源记录'
}
const jobs = ref<JobListItem[]>([])
const snapshots = ref<JobSnapshot[]>([])
const versions = ref<(ResumeVersion & { label: string })[]>([])
const revisions = ref<{ id: string; revision_no: number }[]>([])
const reports = ref<Report[]>([])
const jobId = ref('')
const snapshotId = ref('')
const revisionId = ref('')
const versionId = ref('')
/** 首次读取匹配所需输入失败时留在页面内，并提供明确的重试入口。 */
const loadError = ref<ParsedServerError | null>(null)
/** 用户主动切换或生成报告失败时，只有需就地处理的原因才保留为页面提示。 */
const actionError = ref<ParsedServerError | null>(null)
const busy = ref(false)
const requirementColumns = [
  { title: 'JD 原文条件', key: 'text', width: '34%' },
  { title: '档案事实（字面匹配）', key: 'evidence', width: '34%' },
  { title: '判断边界', dataIndex: 'explanation', key: 'explanation' },
]

/** 将服务端的补充原因和请求编号组合为可追踪的说明文本。 */
function describeError(error: ParsedServerError | null): string | undefined {
  if (error === null) return undefined
  const parts = [...error.general]
  if (error.requestId !== null) parts.push(`错误编号：${error.requestId}`)
  return parts.length === 0 ? undefined : parts.join(' ')
}

const loadErrorDescription = computed(() => describeError(loadError.value))
const actionErrorDescription = computed(() => describeError(actionError.value))

/** 切换职位立即清空旧快照，慢响应不能覆盖新选择。 */
async function selectJob(): Promise<void> {
  const selected = jobId.value
  snapshots.value = []
  snapshotId.value = ''
  actionError.value = null
  try {
    const [detail, results] = await Promise.all([fetchJob(selected), listSnapshots(selected)])
    if (jobId.value === selected) {
      snapshots.value = detail.latest_snapshot && !results.some(s => s.id === detail.latest_snapshot?.id) ? [detail.latest_snapshot, ...results] : results
      snapshotId.value = detail.latest_snapshot?.id ?? ''
    }
  } catch (error: unknown) {
    if (jobId.value === selected) actionError.value = resolveActionFailure(error, '读取职位快照')
  }
}

/** 加载匹配输入与历史报告；失败时不能把页面伪装成空数据。 */
async function load(): Promise<void> {
  loadError.value = null
  try {
    jobs.value = await listJobs()
    reports.value = await requestV1('/matches')
    revisions.value = await requestV1('/profile/revisions')
    const resumes = await listResumes()
    versions.value = (await Promise.all(resumes.map(async resume =>
      (await listVersions(resume.id)).map(version => ({ ...version, label: `${resume.name} · v${version.version_no}` })),
    ))).flat()
  } catch (error: unknown) {
    loadError.value = parseServerError(error)
  }
}

async function analyze(): Promise<void> {
  if (busy.value) return
  busy.value = true
  actionError.value = null
  try {
    const revision = versionId.value ? versions.value.find(version => version.id === versionId.value)?.profile_revision_id : revisionId.value
    await requestV1('/matches', {
      init: {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_snapshot_id: snapshotId.value, profile_revision_id: revision, resume_version_id: versionId.value || null }),
      },
    })
    reports.value = await requestV1('/matches')
  } catch (error: unknown) {
    actionError.value = resolveActionFailure(error, '生成匹配报告')
  } finally {
    busy.value = false
  }
}
onMounted(() => { void load() })
</script>
<template>
  <section class="matching-view">
    <header class="page-header"><div><p class="page-eyebrow">MATCHING</p><h1>匹配分析</h1><p class="page-subtitle">逐条核对职位条件、证据与未知项。</p></div><a-button data-testid="reload" @click="load">刷新</a-button></header>
    <a-alert type="info" show-icon message="匹配报告是辅助判断" description="当前使用本地字面检索：命中的只说明档案里有这条技能事实（其中包含本人填写、未验证的内容），不代表能力、熟练度、年限或整项条件已核实，也不代表录用概率。" class="section-gap" data-testid="matching-boundary" />
    <a-alert v-if="loadError" type="error" show-icon :message="loadError.message" :description="loadErrorDescription" class="section-gap" data-testid="load-error" role="alert"><template #action><a-button size="small" data-testid="retry-load" @click="load">重新加载</a-button></template></a-alert>
    <a-alert v-if="actionError" type="error" show-icon closable :message="actionError.message" :description="actionErrorDescription" class="section-gap" data-testid="action-error" role="alert" @close="actionError = null" />
    <a-card title="生成报告" class="section-gap">
      <a-form layout="vertical" @submit.prevent="analyze">
        <div class="form-grid">
          <a-form-item label="职位" required><a-select v-model:value="jobId" data-testid="matching-job" placeholder="选择职位" :options="jobs.map(j => ({ value: j.id, label: `${j.company_name} · ${j.title}` }))" @change="selectJob" /></a-form-item>
          <a-form-item label="JD 快照" required><a-select v-model:value="snapshotId" data-testid="matching-snapshot" placeholder="选择快照（默认当前保存 JD）" :options="snapshots.map(s => ({ value: s.id, label: `${s.posting_id} · ${new Date(s.captured_at).toLocaleString()}` }))" /></a-form-item>
          <a-form-item label="匹配对象"><a-select v-model:value="versionId" :options="[{ value: '', label: '个人资料' }, ...versions.map(v => ({ value: v.id, label: v.label }))]" /></a-form-item>
          <a-form-item v-if="!versionId" label="资料修订" required><a-select v-model:value="revisionId" placeholder="选择修订" :options="revisions.map(r => ({ value: r.id, label: `修订 ${r.revision_no}` }))" /></a-form-item>
        </div>
        <a-button type="primary" :loading="busy" :disabled="!snapshotId || (!versionId && !revisionId)" data-testid="analyze" @click="analyze">生成并保存报告</a-button>
      </a-form>
    </a-card>
    <a-card title="历史报告" class="section-gap">
      <a-empty v-if="!reports.length" description="暂无分析报告" />
      <a-collapse v-else accordion>
        <a-collapse-panel v-for="report in reports" :key="report.id" :header="`${new Date(report.created_at).toLocaleString()} · ${report.match_kind === 'PROFILE' ? '资料匹配' : '简历匹配'}`">
          <p class="report-source">JD 快照：{{ report.job_snapshot_id }} · 资料修订：{{ report.profile_revision_id }}</p>
          <a-table :columns="requirementColumns" :data-source="report.report_json.requirements" :pagination="false" size="small" :row-key="(_row: unknown, index: number) => index">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'text'"><a-tag v-if="record.hard" color="orange">硬性条件</a-tag>{{ record.text }}</template>
              <template v-else-if="column.key === 'evidence'">
                <span v-if="!record.evidence.length" class="muted">未找到档案事实</span>
                <!-- 命中事实的状态与来源逐条显示：读者据此判断可信度，而不是把它当作已核实。 -->
                <div v-for="e in record.evidence" v-else :key="e.fact_id" class="matched-fact">
                  <div>{{ e.name }} · {{ claimStatusLabel(e.claim_status) }}</div>
                  <div class="muted">{{ evidenceSourceLabel(e) }}</div>
                </div>
              </template>
              <template v-else-if="column.key === 'explanation'">
                <a-tag :color="record.status === 'UNKNOWN' ? 'default' : 'blue'" data-testid="match-status">
                  {{ matchStatusLabel(record.status) }}
                </a-tag>
                {{ record.explanation }}
              </template>
            </template>
          </a-table>
          <a-alert v-if="report.report_json.uncertainties.length" type="warning" class="uncertainties"><template #message>仍需确认</template><template #description><ul><li v-for="note in report.report_json.uncertainties" :key="note">{{ note }}</li></ul></template></a-alert>
        </a-collapse-panel>
      </a-collapse>
    </a-card>
  </section>
</template>
<style scoped>
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.report-source, .muted { color: var(--ja-color-muted); font-size: 12px; }
/* 一条命中事实占两行：事实与状态一行，来源说明一行（次要信息下沉，避免读成"已核实"）。 */
.matched-fact { margin-bottom: 4px; }
.uncertainties { margin-top: 16px; }
.uncertainties ul { margin: 0; padding-left: 18px; }
@media (max-width: 800px) { .form-grid { grid-template-columns: 1fr; } }
</style>
