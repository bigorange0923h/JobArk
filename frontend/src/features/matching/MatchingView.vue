<script setup lang="ts">
/** 可解释匹配入口：选择不可变输入，逐条阅读证据与未知项。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { fetchProfile } from '@/shared/api/profile'
import { Modal } from 'ant-design-vue'
import { requestV1 } from '@/shared/api/client'
import { fetchJob, listJobs, listSnapshots, type JobListItem, type JobSnapshot } from '@/shared/api/job'
import { listResumes, listVersions, type ResumeVersion } from '@/shared/api/resume'
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'
import CompanyResearchPanel from '@/features/job/CompanyResearchPanel.vue'
import { listAiProviders } from '@/shared/api/ai'
interface Report { id: string; created_at: string; match_kind: string; job_snapshot_id: string; profile_revision_id: string; resume_version_id: string | null; is_stale?: boolean | null; report_json: { reference_score?: { lower: number; upper: number; coverage: number; single_score: number | null; recommendation: string; conditions: { id: string; dimension: string; text: string; status: string; ratio: number | null; weight: number; explanation: string }[] }; decision?: { verdict: string }; priority?: { matched: boolean }; preparation?: string[]; questions?: string[]; data_warnings?: string[]; requirements: { text: string; hard: boolean; status: string; explanation: string; evidence: { fact_id: string; name: string; claim_status: string; evidence_title?: string; fact_quote?: string | null; source_support?: string }[] }[]; uncertainties: string[] } }
interface ParseResult { id: string; status: string }
const route = useRoute()
const useSavedProfile = ref(true)
const profileExists = ref(true)
const aiOpen = ref(false)
const aiProviderLabel = ref('尚未读取配置')
const expectedService = ref<string | null>(null)
const expectedModel = ref<string | null>(null)
/** 外发前显示实际所选服务商和模型；配置读取失败不触发外发。 */
async function openAiConfirmation(): Promise<void> {
  try {
    const providers = await listAiProviders()
    const selected = providers.find(provider => provider.models.some(model => model.is_default))
    expectedService.value = selected?.base_url ?? null
    expectedModel.value = selected?.models.find(model => model.is_default)?.remote_model_id ?? null
    aiProviderLabel.value = selected ? `${selected.name} · ${selected.models.find(model => model.is_default)?.name} · ${selected.base_url}` : '尚未配置默认模型'
    aiOpen.value = true
  } catch (cause) { actionError.value = resolveActionFailure(cause, '读取大模型服务配置') }
}
const parses = ref<ParseResult[]>([])
const parseId = ref('')

/**
 * 命中状态文案。
 *
 * 措辞刻意停在"档案里有这条事实"这一层：命中可能是本人填写、未验证的技能，不能读成能力、
 * 熟练度、年限或整项条件已经核实。`EVIDENCE_FOUND` 是语义调整前写入历史报告的值，按同样意思展示。
 */
const MATCH_STATUS_LABELS: Record<string, string> = {
  STRATEGY_COMPARISON: '已保存字段与当次策略比较',
  CONDITION_ASSESSED: '模型条件评估（依据仍需核对）',
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
    try { revisions.value = await requestV1('/profile/revisions') } catch (cause) { if (parseServerError(cause).code === 'RESOURCE_NOT_FOUND') revisions.value = []; else throw cause }
    revisionId.value ||= revisions.value[0]?.id ?? ''
    try { await fetchProfile(); profileExists.value = true } catch (cause) { if (parseServerError(cause).code === 'RESOURCE_NOT_FOUND') profileExists.value = false; else throw cause }
    const resumes = await listResumes()
    versions.value = (await Promise.all(resumes.map(async resume =>
      (await listVersions(resume.id)).map(version => ({ ...version, label: `${resume.name} · v${version.version_no}` })),
    ))).flat()
    if (typeof route?.query.job === 'string' && jobs.value.some(job => job.id === route.query.job)) { jobId.value = route.query.job; await selectJob() }
  } catch (error: unknown) {
    loadError.value = parseServerError(error)
  }
}

async function analyze(engine: 'LOCAL' | 'AI' = 'LOCAL'): Promise<void> {
  if (busy.value) return
  busy.value = true
  actionError.value = null
  try {
    const selectedSnapshot = snapshotId.value
    const selectedJob = jobId.value
    const revision = versionId.value ? versions.value.find(version => version.id === versionId.value)?.profile_revision_id : useSavedProfile.value ? (await requestV1<{ id: string }>('/profile/revisions', { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: 'JD 分析固定当前已保存资料' }) } })).id : revisionId.value
    const selectedParse = parseId.value || (await requestV1<ParseResult>(`/job-snapshots/${selectedSnapshot}/parses`, { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ engine: 'LOCAL' }) } })).id
    await requestV1('/matches', {
      init: {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_snapshot_id: selectedSnapshot, profile_revision_id: revision, resume_version_id: versionId.value || null, parse_result_id: selectedParse, engine, confirm_external: engine === 'AI', expected_service: expectedService.value, expected_model: expectedModel.value }),
      },
    })
    const results = await requestV1<Report[]>('/matches')
    if (selectedSnapshot === snapshotId.value && selectedJob === jobId.value) reports.value = results
    aiOpen.value = false
  } catch (error: unknown) {
    actionError.value = resolveActionFailure(error, '生成匹配报告')
  } finally {
    busy.value = false
  }
}
onMounted(() => { void load() })
/** 解析引用随快照重新读取，跨快照旧引用不能继续使用。 */
watch(snapshotId, async selected => {
  parses.value = []; parseId.value = ''
  if (!selected) return
  try {
    const rows = await requestV1<ParseResult[]>(`/job-snapshots/${selected}/parses`)
    if (snapshotId.value === selected) { parses.value = rows.filter(row => row.status === 'PARSED'); parseId.value = parses.value[0]?.id ?? '' }
  } catch (cause) { if (snapshotId.value === selected) actionError.value = resolveActionFailure(cause, '读取解析历史') }
})
</script>
<template>
  <section class="matching-view">
    <header class="page-header"><div><p class="page-eyebrow">MATCHING</p><h1>匹配分析</h1><p class="page-subtitle">逐条核对职位条件、证据与未知项。</p></div><a-button data-testid="reload" @click="load">刷新</a-button></header>
    <a-alert type="info" show-icon message="匹配报告是辅助判断" description="本地分析提供有限字面线索；大模型逐项评估也需核对事实出处。缺记录不等于不满足，引用不代表独立核验，参考区间不代表录用概率。" class="section-gap" data-testid="matching-boundary" />
    <a-alert v-if="loadError" type="error" show-icon :message="loadError.message" :description="loadErrorDescription" class="section-gap" data-testid="load-error" role="alert"><template #action><a-button size="small" data-testid="retry-load" @click="load">重新加载</a-button></template></a-alert>
    <a-alert v-if="actionError" type="error" show-icon closable :message="actionError.message" :description="actionErrorDescription" class="section-gap" data-testid="action-error" role="alert" @close="actionError = null" />
    <a-card title="生成报告" class="section-gap">
      <a-alert v-if="!profileExists" type="info" message="JD 可以先保存和解析；个性化分析请先创建个人档案。"><template #action><RouterLink to="/profile">前往个人资料</RouterLink></template></a-alert>
      <a-form layout="vertical" @submit.prevent="analyze()">
        <div class="form-grid">
          <a-form-item label="职位" required><a-select v-model:value="jobId" :disabled="busy" data-testid="matching-job" placeholder="选择职位" :options="jobs.map(j => ({ value: j.id, label: `${j.company_name ?? '公司待补充'} · ${j.title ?? '职位待补充'}` }))" @change="selectJob" /></a-form-item>
          <a-form-item label="JD 快照" required><a-select v-model:value="snapshotId" data-testid="matching-snapshot" placeholder="选择快照（默认当前保存 JD）" :options="snapshots.map(s => ({ value: s.id, label: `${s.posting_id} · ${new Date(s.captured_at).toLocaleString()}` }))" /></a-form-item>
          <a-form-item label="匹配对象"><a-select v-model:value="versionId" :options="[{ value: '', label: '个人资料' }, ...versions.map(v => ({ value: v.id, label: v.label }))]" /></a-form-item>
          <a-form-item v-if="!versionId" label="资料输入"><a-checkbox v-model:checked="useSavedProfile">使用当前已保存资料（草稿不参与）</a-checkbox><a-select v-if="!useSavedProfile" v-model:value="revisionId" placeholder="选择历史修订" :options="revisions.map(r => ({ value: r.id, label: `修订 ${r.revision_no}` }))" /></a-form-item>
          <a-form-item label="成功解析产物" extra="未选择时会独立保存本地解析；分析失败不撤销 JD 保存。"><a-select v-model:value="parseId" :options="[{ value: '', label: '创建本地解析' }, ...parses.map(p => ({ value: p.id, label: p.id }))]" /></a-form-item>
        </div>
        <a-space wrap><a-button type="primary" :loading="busy" :disabled="!profileExists || !snapshotId || (!versionId && !useSavedProfile && !revisionId)" data-testid="analyze" @click="analyze()">本地分析并保存</a-button><a-button :disabled="busy || !profileExists || !snapshotId" @click="openAiConfirmation">大模型条件分析</a-button></a-space>
        <Modal v-model:open="aiOpen" title="确认外发条件分析" :confirm-loading="busy" ok-text="确认发送并分析" cancel-text="继续本地路径" @ok="analyze('AI')"><p>大模型服务：{{ aiProviderLabel }}</p><p>JD 和必要履历事实摘要将发送至上述大模型服务，用于条件对照。不会发送个人联系方式。资料可能含项目内容，请核对后继续。</p><RouterLink to="/ai-models">查看服务商配置</RouterLink><a-alert v-if="actionError" type="error" :message="actionError.message" /></Modal>
      </a-form>
    </a-card>
    <CompanyResearchPanel v-if="jobId" :key="jobId" :job-id="jobId" />
    <a-card title="历史报告" class="section-gap">
      <a-empty v-if="!reports.length" description="暂无分析报告" />
      <a-collapse v-else accordion>
        <a-collapse-panel v-for="report in reports" :key="report.id" :header="`${new Date(report.created_at).toLocaleString()} · ${report.match_kind === 'PROFILE' ? '资料匹配' : '简历匹配'}`">
          <p class="report-source">JD 快照：{{ report.job_snapshot_id }} · 资料修订：{{ report.profile_revision_id }}</p>
          <a-alert v-if="report.is_stale" type="warning" message="相关输入已变化，这是历史报告；请重新分析。" />
          <template v-if="report.report_json.reference_score">
            <h3>{{ report.report_json.reference_score.recommendation }}</h3>
            <a-alert v-if="report.report_json.data_warnings?.length" type="info" message="建议补充资料（选填缺失不代表能力不足）" data-testid="data-warnings"><template #description><ul><li v-for="note in report.report_json.data_warnings" :key="note">{{ note }}</li></ul><RouterLink to="/profile">补充个人资料</RouterLink> · <RouterLink to="/strategy">核对求职策略</RouterLink></template></a-alert>
            <p data-testid="reference-score">{{ report.report_json.reference_score.single_score === null ? '暂不能可靠给出单一分数' : `参考分 ${report.report_json.reference_score.single_score.toFixed(1)} / 10` }} · 范围 {{ report.report_json.reference_score.lower.toFixed(1) }}–{{ report.report_json.reference_score.upper.toFixed(1) }} / 10 · 覆盖率 {{ (report.report_json.reference_score.coverage * 100).toFixed(0) }}%</p>
            <p>策略：{{ report.report_json.decision?.verdict }} · {{ report.report_json.priority?.matched ? '优先名单命中（不抵消限制、不加分）' : '未命中优先名单' }}</p>
            <a-list :data-source="report.report_json.reference_score.conditions"><template #renderItem="{ item }"><a-list-item>{{ item.dimension }} · {{ item.text }} · 权重 {{ item.weight.toFixed(2) }} · {{ item.status === 'UNKNOWN' ? '待确认' : item.ratio }}：{{ item.explanation }}</a-list-item></template></a-list>
            <p v-for="item in report.report_json.preparation ?? []" :key="item">准备：{{ item }}</p><p v-for="item in report.report_json.questions ?? []" :key="item">追问：{{ item }}</p>
          </template>
          <a-table :columns="requirementColumns" :data-source="report.report_json.requirements" :pagination="false" size="small" :row-key="(_row: unknown, index: number) => index">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'text'"><a-tag v-if="record.hard" color="orange">硬性条件</a-tag><a-tag v-if="record.relation === 'OR'">替代条件（待确认）</a-tag>{{ record.text }}<div v-if="record.source_start != null" class="muted">原文字符位置：{{ record.source_start }}–{{ record.source_end }}</div></template>
              <template v-else-if="column.key === 'evidence'">
                <span v-if="!record.evidence.length" class="muted">未找到档案事实</span>
                <!-- 命中事实的状态与来源逐条显示：读者据此判断可信度，而不是把它当作已核实。 -->
                <div v-for="e in record.evidence" v-else :key="e.fact_id" class="matched-fact">
                  <div>{{ e.name }} · {{ claimStatusLabel(e.claim_status) }}</div>
                  <div class="muted">{{ evidenceSourceLabel(e) }}</div>
                  <div v-if="e.fact_quote" class="muted">判断摘录：{{ e.fact_quote }}</div>
                  <div v-if="e.source_support" class="muted">{{ e.source_support === 'EXCERPT_SUPPORTED' ? '来源摘录支持这一片段，能力仍未独立核验' : e.source_support === 'SOURCE_ATTACHED' ? '有关联来源，当前摘录未覆盖这一判断' : '本人陈述' }}</div>
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
