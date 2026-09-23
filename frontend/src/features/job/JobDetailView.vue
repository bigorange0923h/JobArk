<script setup lang="ts">
/** 职位详情、历史 JD 和申请创建；历史内容只读。 */
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchJob, listSnapshots, updateJob, saveSnapshot, type JobOpportunity, type JobSnapshot } from '@/shared/api/job'
import { listResumes, listVersions, type ResumeVersion } from '@/shared/api/resume'
import { createApplication } from '@/shared/api/application'
import { parseServerError } from '@/shared/forms/serverErrors'
import { requestV1 } from '@/shared/api/client'
const props = defineProps<{ jobId: string }>()
const router = useRouter()
const job = ref<JobOpportunity | null>(null)
const snapshots = ref<JobSnapshot[]>([])
const versions = ref<(ResumeVersion & { label: string })[]>([])
const selectedSnapshot = ref('')
const selectedVersion = ref('')
const repeat = ref(false)
const newJd = ref('')
const posting = ref('')
const error = ref('')
const busy = ref(false)
const external = ref(false)
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
  } catch (e) { if (selectedSnapshot.value === snapshotId) error.value = parseServerError(e).message }
}
watch(selectedSnapshot, loadParses)
/** 解析前确认外部发送，结果与原始快照并存。 */
async function parse(engine: 'LOCAL' | 'AI'): Promise<void> {
  if (busy.value || !selectedSnapshot.value) return
  busy.value = true; error.value = ''
  try { await requestV1(`/job-snapshots/${selectedSnapshot.value}/parses`, { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ engine, confirm_external: external.value }) } }); await loadParses() }
  catch(e) { error.value = parseServerError(e).message }
  finally { busy.value = false }
}
/** 重新读取服务端状态，保留错误供用户处理。 */
async function load(): Promise<void> {
  try {
    job.value = await fetchJob(props.jobId)
    snapshots.value = await listSnapshots(props.jobId)
    selectedSnapshot.value ||= snapshots.value[0]?.id ?? ''
    posting.value ||= job.value.postings[0]?.id ?? ''
    const resumes = await listResumes()
    versions.value = (await Promise.all(resumes.map(async r => (await listVersions(r.id)).map(v => ({ ...v, label: `${r.name} · v${v.version_no}` }))))).flat()
  } catch (e) { error.value = parseServerError(e).message }
}
/** 执行写入且禁止重复点击；失败不清空用户输入。 */
async function action(kind: 'save' | 'snapshot' | 'apply'): Promise<void> {
  if (!job.value || busy.value) return
  busy.value = true; error.value = ''
  try {
    if (kind === 'save') job.value = await updateJob(props.jobId, { version: job.value.version, title: job.value.title, location: job.value.location, notes: job.value.notes, status: job.value.status })
    if (kind === 'snapshot') { await saveSnapshot(props.jobId, posting.value, newJd.value); newJd.value = ''; await load() }
    if (kind === 'apply') { await createApplication({ job_opportunity_id: props.jobId, job_snapshot_id: selectedSnapshot.value, resume_version_id: selectedVersion.value, confirm_repeat: repeat.value }); await router.push({ name: 'applications' }) }
  } catch (e) { error.value = parseServerError(e).message }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <section class="job-detail-view">
    <header class="page-header"><div><RouterLink to="/jobs" class="back-link">← 返回职位列表</RouterLink><h1>{{ job?.title ?? '职位详情' }}</h1><p class="page-subtitle">{{ job?.company.name ?? '职位资料与 JD 历史' }}</p></div><a-tag v-if="job" :color="job.status === 'ACTIVE' ? 'blue' : 'default'">{{ job.status === 'ACTIVE' ? '处理中' : '已归档' }}</a-tag></header>
    <a-alert v-if="error" type="error" show-icon :message="error" class="section-gap" role="alert"><template #action><a-button size="small" @click="load">重新加载</a-button></template></a-alert>
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
            <a-space wrap><a-button :loading="busy" :disabled="!selectedSnapshot" @click="parse('LOCAL')">本地提取条件</a-button><a-button :loading="busy" :disabled="!external || !selectedSnapshot" @click="parse('AI')">AI 解析</a-button></a-space>
            <div class="confirm-line"><a-checkbox v-model:checked="external">同意将所选 JD 原文发送到已配置的 AI 网关</a-checkbox></div>
            <a-collapse v-if="parseResults.length" class="parse-results"><a-collapse-panel v-for="result in parseResults" :key="result.id" :header="result.status === 'FAILED' ? '解析失败，原文已保留' : '解析结果'"><a-alert v-if="result.failure_code" type="warning" :message="`解析未成功，请检查网关配置或稍后重试。错误码：${result.failure_code}`" /><template v-if="result.result_json"><ul><li v-for="(item, index) in result.result_json.requirements" :key="index">{{ item.hard ? '明确强制：' : '' }}{{ item.text }}</li></ul><p v-for="(item, index) in result.result_json.uncertainties" :key="index">{{ item }}</p></template></a-collapse-panel></a-collapse>
          </a-card>
          <a-card title="创建申请记录" class="section-gap"><p class="card-hint">使用所选 JD 和正式简历版本；创建记录不会自动投递。</p><a-form layout="vertical" @submit.prevent="action('apply')"><a-form-item label="简历版本" required><a-select v-model:value="selectedVersion" placeholder="请选择正式版本" :options="versions.map(v => ({ value: v.id, label: v.label }))" /></a-form-item><a-form-item><a-checkbox v-model:checked="repeat">如已有申请，确认新增一次申请尝试</a-checkbox></a-form-item><a-button type="primary" :loading="busy" :disabled="!selectedVersion || !selectedSnapshot" @click="action('apply')">创建申请</a-button></a-form></a-card>
        </div>
      </div>
    </template>
  </section>
</template>
<style scoped>
.back-link { display: inline-block; margin-bottom: 12px; font-size: 12px; }
.card-hint { margin: 0 0 16px; }
.detail-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(320px, 1fr); gap: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.jd-original { max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; font-size: 12px; line-height: 1.7; }
.confirm-line { margin-top: 14px; }
.parse-results { margin-top: 18px; }
@media (max-width: 1060px) { .detail-grid { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .form-grid { grid-template-columns: 1fr; } }
</style>
