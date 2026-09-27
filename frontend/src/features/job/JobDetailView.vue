<script setup lang="ts">
/** 职位详情、历史 JD 和申请创建；历史内容只读。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchJob, listSnapshots, updateJob, saveSnapshot, type JobOpportunity, type JobSnapshot } from '@/shared/api/job'
import { listResumes, listVersions, type ResumeVersion } from '@/shared/api/resume'
import { createApplication } from '@/shared/api/application'
import { ApiError, requestV1 } from '@/shared/api/client'
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'
const props = defineProps<{ jobId: string }>()
const router = useRouter()
const job = ref<JobOpportunity | null>(null)
const snapshots = ref<JobSnapshot[]>([])
const versions = ref<(ResumeVersion & { label: string })[]>([])
const selectedSnapshot = ref('')
const selectedVersion = ref('')
const newJd = ref('')
const posting = ref('')
/** 页面初始加载失败：留在页面上并保留重试入口。 */
const loadError = ref<ParsedServerError | null>(null)
/** 用户操作失败：多数情况不需要占用页面位置，只有需要就地处理的原因才内联展示。 */
const actionError = ref<ParsedServerError | null>(null)
const busy = ref(false)
/** 两类高影响操作都在弹窗确认后才实际请求。 */
const confirmAiParseOpen = ref(false)
const confirmRepeatOpen = ref(false)

/** 把解析后的错误拼成"补充原因 + 错误编号"的说明文本。 */
function describeError(error: ParsedServerError | null): string | undefined {
  if (error === null) return undefined
  const parts = [...error.general]
  if (error.requestId !== null) parts.push(`错误编号：${error.requestId}`)
  return parts.length === 0 ? undefined : parts.join(' ')
}

const loadErrorDescription = computed(() => describeError(loadError.value))
const actionErrorDescription = computed(() => describeError(actionError.value))

interface ParseResult {
  id: string
  status: string
  failure_code: string | null
  result_json: { requirements: { text: string; hard: boolean; source_quote: string }[]; uncertainties: string[] } | null
}
const parseResults = ref<ParseResult[]>([])
/** 切换快照时清除旧结果，并防止慢响应覆盖新选择。 */
async function loadParses(): Promise<void> {
  const snapshotId = selectedSnapshot.value
  parseResults.value = []
  if (!snapshotId) return
  try {
    const results = await requestV1<ParseResult[]>(`/job-snapshots/${snapshotId}/parses`)
    if (selectedSnapshot.value === snapshotId) parseResults.value = results
  } catch (error: unknown) {
    if (selectedSnapshot.value === snapshotId) actionError.value = resolveActionFailure(error, '读取 JD 解析结果')
  }
}
watch(selectedSnapshot, loadParses)
/** 解析前确认外部发送，结果与原始快照并存。 */
async function parse(engine: 'LOCAL' | 'AI', confirmExternal = false): Promise<void> {
  if (busy.value || !selectedSnapshot.value) return
  if (engine === 'AI' && !confirmExternal) {
    confirmAiParseOpen.value = true
    return
  }
  busy.value = true; actionError.value = null
  try { await requestV1(`/job-snapshots/${selectedSnapshot.value}/parses`, { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ engine, confirm_external: confirmExternal }) } }); confirmAiParseOpen.value = false; await loadParses() }
  catch (error: unknown) { actionError.value = resolveActionFailure(error, '解析 JD') }
  finally { busy.value = false }
}
/** 重新读取服务端状态；加载失败留在页面上，用户可直接重试。 */
async function load(): Promise<void> {
  loadError.value = null
  try {
    job.value = await fetchJob(props.jobId)
    snapshots.value = await listSnapshots(props.jobId)
    selectedSnapshot.value ||= snapshots.value[0]?.id ?? ''
    posting.value ||= job.value.postings[0]?.id ?? ''
    const resumes = await listResumes()
    versions.value = (await Promise.all(resumes.map(async r => (await listVersions(r.id)).map(v => ({ ...v, label: `${r.name} · v${v.version_no}` }))))).flat()
  } catch (error: unknown) { loadError.value = parseServerError(error) }
}
/** 执行写入且禁止重复点击；失败不清空用户输入。 */
async function action(kind: 'save' | 'snapshot' | 'apply', confirmRepeat = false): Promise<void> {
  if (!job.value || busy.value) return
  busy.value = true; actionError.value = null
  const label = kind === 'save' ? '保存职位修改' : kind === 'snapshot' ? '保存 JD 快照' : '创建申请'
  try {
    if (kind === 'save') job.value = await updateJob(props.jobId, { version: job.value.version, title: job.value.title, location: job.value.location, notes: job.value.notes, status: job.value.status })
    if (kind === 'snapshot') { await saveSnapshot(props.jobId, posting.value, newJd.value); newJd.value = ''; await load() }
    if (kind === 'apply') { await createApplication({ job_opportunity_id: props.jobId, job_snapshot_id: selectedSnapshot.value, resume_version_id: selectedVersion.value, confirm_repeat: confirmRepeat }); confirmRepeatOpen.value = false; await router.push({ name: 'applications' }) }
  } catch (error: unknown) {
    // 只有稳定错误码明确表示重复时才弹确认框，不能把版本等其他冲突误当作重复申请。
    if (kind === 'apply' && error instanceof ApiError && error.code === 'DUPLICATE_APPLICATION' && !confirmRepeat) confirmRepeatOpen.value = true
    else actionError.value = resolveActionFailure(error, label)
  }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <section class="job-detail-view">
    <header class="page-header"><div><RouterLink to="/jobs" class="back-link">← 返回职位列表</RouterLink><h1>{{ job?.title ?? '职位详情' }}</h1><p class="page-subtitle">{{ job?.company.name ?? '职位资料与 JD 历史' }}</p></div><a-tag v-if="job" :color="job.status === 'ACTIVE' ? 'blue' : 'default'">{{ job.status === 'ACTIVE' ? '处理中' : '已归档' }}</a-tag></header>
    <a-alert v-if="loadError" type="error" show-icon :message="loadError.message" :description="loadErrorDescription" class="section-gap" data-testid="load-error" role="alert"><template #action><a-button size="small" data-testid="retry-load" @click="load">重新加载</a-button></template></a-alert>
    <a-alert v-if="actionError" type="error" show-icon closable :message="actionError.message" :description="actionErrorDescription" class="section-gap" data-testid="action-error" role="alert" @close="actionError = null" />
    <template v-if="job">
      <div class="detail-grid">
        <div class="primary-column">
          <a-card title="职位信息" class="section-gap">
            <a-form layout="vertical" @submit.prevent="action('save')">
              <div class="form-grid"><a-form-item label="职位" required><a-input v-model:value="job.title" :maxlength="200" /></a-form-item><a-form-item label="地点"><a-input v-model:value="job.location" :maxlength="200" /></a-form-item></div>
              <a-form-item label="备注"><a-textarea v-model:value="job.notes" :rows="3" :maxlength="10000" /></a-form-item>
              <a-form-item label="状态"><a-select v-model:value="job.status" :options="[{ value: 'ACTIVE', label: '处理中' }, { value: 'ARCHIVED', label: '已归档' }]" /></a-form-item>
              <a-button type="primary" :loading="busy" :disabled="!job.title.trim()" @click="action('save')">保存修改</a-button>
            </a-form>
          </a-card>
          <a-card title="JD 历史" class="section-gap">
            <a-empty v-if="!snapshots.length" description="暂无快照" />
            <a-collapse v-else accordion><a-collapse-panel v-for="snapshot in snapshots" :key="snapshot.id" :header="new Date(snapshot.captured_at).toLocaleString()"><pre class="jd-original">{{ snapshot.raw_jd }}</pre></a-collapse-panel></a-collapse>
            <a-divider />
            <a-form layout="vertical" @submit.prevent="action('snapshot')"><a-form-item label="来源页面"><a-select v-model:value="posting" :options="job.postings.map(p => ({ value: p.id, label: p.canonical_url ?? '手工录入' }))" /></a-form-item><a-form-item label="更新 JD 原文" required><a-textarea v-model:value="newJd" :rows="6" :maxlength="100000" /></a-form-item><a-button type="primary" :loading="busy" :disabled="!newJd.trim()" @click="action('snapshot')">保存新快照</a-button></a-form>
          </a-card>
        </div>
        <div class="secondary-column">
          <a-card title="JD 解析" class="section-gap">
            <p class="card-hint">提取条件后仍需人工核对，原始 JD 始终保留。</p>
            <a-form-item label="选择 JD 快照"><a-select v-model:value="selectedSnapshot" :disabled="busy" :options="snapshots.map(s => ({ value: s.id, label: new Date(s.captured_at).toLocaleString() }))" /></a-form-item>
            <a-space wrap><a-button :loading="busy" :disabled="!selectedSnapshot" @click="parse('LOCAL')">本地提取条件</a-button><a-button :loading="busy" :disabled="!selectedSnapshot" @click="parse('AI')">AI 解析</a-button></a-space>
            <a-collapse v-if="parseResults.length" class="parse-results"><a-collapse-panel v-for="result in parseResults" :key="result.id" :header="result.status === 'FAILED' ? '解析失败，原文已保留' : '解析结果'"><a-alert v-if="result.failure_code" type="warning" :message="`解析未成功，请检查大模型服务配置或稍后重试。错误码：${result.failure_code}`" /><template v-if="result.result_json"><ul><li v-for="(item, index) in result.result_json.requirements" :key="index">{{ item.hard ? '明确强制：' : '' }}{{ item.text }}</li></ul><p v-for="(item, index) in result.result_json.uncertainties" :key="index">{{ item }}</p></template></a-collapse-panel></a-collapse>
          </a-card>
          <a-card title="创建申请记录" class="section-gap"><p class="card-hint">使用所选 JD 和正式简历版本；创建记录不会自动投递。</p><a-form layout="vertical" @submit.prevent="action('apply')"><a-form-item label="简历版本" required><a-select v-model:value="selectedVersion" placeholder="请选择正式版本" :options="versions.map(v => ({ value: v.id, label: v.label }))" /></a-form-item><a-button type="primary" :loading="busy" :disabled="!selectedVersion || !selectedSnapshot" @click="action('apply')">创建申请</a-button></a-form></a-card>
        </div>
      </div>
      <a-modal v-if="confirmAiParseOpen" :open="confirmAiParseOpen" title="确认发送 JD 原文" :confirm-loading="busy" ok-text="确认发送并解析" cancel-text="取消" @ok="parse('AI', true)" @cancel="confirmAiParseOpen = false">
        <div data-testid="confirm-ai-parse-dialog">
          <p>将把当前选择的 JD 原文发送到已配置的大模型服务，用于提取职位条件。</p>
          <p class="confirm-hint">JD 可能包含联系人、内部项目或其他敏感信息；原始 JD 会保留，解析结果仍需人工核对。</p>
          <a-alert v-if="actionError" type="error" show-icon :message="actionError.message" :description="actionErrorDescription" class="confirm-error" />
        </div>
      </a-modal>
      <a-modal v-if="confirmRepeatOpen" :open="confirmRepeatOpen" title="发现已有申请记录" :confirm-loading="busy" ok-text="确认创建新的申请尝试" cancel-text="取消" @ok="action('apply', true)" @cancel="confirmRepeatOpen = false">
        <div data-testid="confirm-repeat-dialog">
          <p>此职位已有申请记录。继续会创建一条新的申请尝试，并保留原有记录。</p>
          <p class="confirm-hint">不会自动投递，也不会覆盖既有申请历史。</p>
          <a-alert v-if="actionError" type="error" show-icon :message="actionError.message" :description="actionErrorDescription" class="confirm-error" />
        </div>
      </a-modal>
    </template>
  </section>
</template>
<style scoped>
.back-link { display: inline-block; margin-bottom: 12px; font-size: 12px; }
.card-hint { margin: 0 0 16px; }
.detail-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(320px, 1fr); gap: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.jd-original { max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; font-size: 12px; line-height: 1.7; }
.parse-results { margin-top: 18px; }
.confirm-hint { color: var(--ja-color-muted); font-size: 13px; line-height: 1.6; }
.confirm-error { margin-top: 12px; }
@media (max-width: 1060px) { .detail-grid { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .form-grid { grid-template-columns: 1fr; } }
</style>
