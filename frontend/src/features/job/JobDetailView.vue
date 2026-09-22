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
  <section>
    <RouterLink to="/jobs">返回职位</RouterLink><h1>职位详情</h1>
    <p v-if="error" role="alert">{{ error }} <button @click="load">重新加载</button></p>
    <template v-if="job">
      <h2>{{ job.company.name }}</h2>
      <form @submit.prevent="action('save')">
        <label>职位 <input v-model="job.title" required maxlength="200"></label>
        <label>地点 <input v-model="job.location" maxlength="200"></label>
        <label>备注 <textarea v-model="job.notes" maxlength="10000" /></label>
        <label>状态 <select v-model="job.status"><option value="ACTIVE">处理中</option><option value="ARCHIVED">已归档</option></select></label>
        <button :disabled="busy">保存修改</button>
      </form>
      <h2>JD 历史</h2>
      <p v-if="!snapshots.length">暂无快照</p>
      <details v-for="snapshot in snapshots" :key="snapshot.id"><summary>{{ new Date(snapshot.captured_at).toLocaleString() }}</summary><pre>{{ snapshot.raw_jd }}</pre></details>
      <form @submit.prevent="action('snapshot')"><label>来源页面 <select v-model="posting"><option v-for="p in job.postings" :key="p.id" :value="p.id">{{ p.canonical_url ?? '手工录入' }}</option></select></label><label>更新 JD 原文 <textarea v-model="newJd" required maxlength="100000" /></label><button :disabled="busy || !newJd.trim()">保存新快照</button></form>
      <label>JD 快照 <select v-model="selectedSnapshot" required :disabled="busy"><option v-for="s in snapshots" :key="s.id" :value="s.id">{{ new Date(s.captured_at).toLocaleString() }}</option></select></label>
      <h2>JD 解析</h2><p>使用上方选中的 JD 快照；提取结果仍需人工核对。</p><button :disabled="busy" @click="parse('LOCAL')">本地提取条件</button><label><input v-model="external" type="checkbox">同意将所选 JD 原文发送到已配置的 AI 网关</label><button :disabled="busy || !external" @click="parse('AI')">AI 解析</button>
      <details v-for="result in parseResults" :key="result.id"><summary>{{ result.status === 'FAILED' ? '解析失败，原文已保留' : '解析结果' }}</summary><p v-if="result.failure_code">解析未成功，请检查网关配置或稍后重试。错误码：{{ result.failure_code }}</p><template v-if="result.result_json"><ul><li v-for="(item, index) in result.result_json.requirements" :key="index">{{ item.hard ? '明确强制：' : '' }}{{ item.text }}</li></ul><p v-for="(item, index) in result.result_json.uncertainties" :key="index">{{ item }}</p></template></details>
      <h2>创建申请记录</h2><p>使用所选 JD 和下方简历版本。记录不会自动投递。</p>
      <form @submit.prevent="action('apply')">
        <label>简历版本 <select v-model="selectedVersion" required><option value="" disabled>请选择正式版本</option><option v-for="v in versions" :key="v.id" :value="v.id">{{ v.label }}</option></select></label>
        <label><input v-model="repeat" type="checkbox">如已有申请，确认新增一次申请尝试</label><button :disabled="busy || !selectedVersion">创建申请</button>
      </form>
    </template>
  </section>
</template>
<style scoped>
section{max-width:70rem}form{display:grid;gap:1rem;padding:1rem;border:1px solid #ddd;margin-bottom:1rem}label{display:grid;gap:.4rem}input,select,textarea,button{font:inherit;padding:.5rem}textarea{min-height:6rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}button{width:fit-content}p[role=alert]{color:#b42318}
</style>
