<script setup lang="ts">
/** 可解释匹配入口：选择不可变输入，逐条阅读证据与未知项。 */
import { onMounted, ref } from 'vue'
import { requestV1 } from '@/shared/api/client'
import { listJobs, listSnapshots, type JobListItem, type JobSnapshot } from '@/shared/api/job'
import { listResumes, listVersions, type ResumeVersion } from '@/shared/api/resume'
import { parseServerError } from '@/shared/forms/serverErrors'
interface Report { id: string; created_at: string; match_kind: string; job_snapshot_id: string; profile_revision_id: string; resume_version_id: string | null; report_json: { requirements: { text: string; hard: boolean; status: string; explanation: string; evidence: { fact_id: string; name: string; claim_status: string }[] }[]; uncertainties: string[] } }
const jobs = ref<JobListItem[]>([])
const snapshots = ref<JobSnapshot[]>([])
const versions = ref<(ResumeVersion & { label: string })[]>([])
const revisions = ref<{ id: string; revision_no: number }[]>([])
const reports = ref<Report[]>([])
const jobId = ref('')
const snapshotId = ref('')
const revisionId = ref('')
const versionId = ref('')
const error = ref('')
const busy = ref(false)
/** 切换职位立即清空旧快照，慢响应不能覆盖新选择。 */
async function selectJob(): Promise<void> {
  const selected = jobId.value
  snapshots.value = []; snapshotId.value = ''
  try {
    const results = await listSnapshots(selected)
    if (jobId.value === selected) { snapshots.value = results; snapshotId.value = results[0]?.id ?? '' }
  } catch(e) { if (jobId.value === selected) error.value = parseServerError(e).message }
}
async function load(): Promise<void> {
  try { jobs.value = await listJobs(); reports.value = await requestV1('/matches'); revisions.value = await requestV1('/profile/revisions'); const resumes = await listResumes(); versions.value = (await Promise.all(resumes.map(async r => (await listVersions(r.id)).map(v => ({...v, label: `${r.name} · v${v.version_no}`}))))).flat() }
  catch(e) { error.value = parseServerError(e).message }
}
async function analyze(): Promise<void> {
  if(busy.value) return
  busy.value = true; error.value = ''
  try { const revision = versionId.value ? versions.value.find(v => v.id === versionId.value)?.profile_revision_id : revisionId.value; await requestV1('/matches', { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_snapshot_id: snapshotId.value, profile_revision_id: revision, resume_version_id: versionId.value || null }) } }); reports.value = await requestV1('/matches') }
  catch(e) { error.value = parseServerError(e).message }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <section><h1>匹配分析</h1><p>本地字面证据检索。展示已有依据与未知项，结果不代表满足全部条件或录用概率。</p><p v-if="error" role="alert">{{ error }}</p>
    <form @submit.prevent="analyze"><label>职位 <select v-model="jobId" required @change="selectJob"><option value="" disabled>选择职位</option><option v-for="j in jobs" :key="j.id" :value="j.id">{{ j.company_name }} · {{ j.title }}</option></select></label><label>JD <select v-model="snapshotId" required><option v-for="s in snapshots" :key="s.id" :value="s.id">{{ s.captured_at }}</option></select></label><label>匹配对象 <select v-model="versionId"><option value="">个人资料</option><option v-for="v in versions" :key="v.id" :value="v.id">{{ v.label }}</option></select></label><label v-if="!versionId">资料修订 <select v-model="revisionId" required><option v-for="r in revisions" :key="r.id" :value="r.id">修订 {{ r.revision_no }}</option></select></label><button :disabled="busy || !snapshotId">生成并保存报告</button></form>
    <p v-if="!reports.length">暂无分析报告。</p><details v-for="report in reports" :key="report.id"><summary>{{ report.created_at }} · {{ report.match_kind === 'PROFILE' ? '资料匹配' : '简历匹配' }}</summary><p>JD：{{ report.job_snapshot_id }} · 资料修订：{{ report.profile_revision_id }}</p><table><thead><tr><th>原文条件</th><th>证据</th><th>判断边界</th></tr></thead><tbody><tr v-for="(row, index) in report.report_json.requirements" :key="index"><td>{{ row.hard ? '明确强制：' : '' }}{{ row.text }}</td><td><span v-if="!row.evidence.length">未知</span><ul v-else><li v-for="e in row.evidence" :key="e.fact_id">{{ e.name }}（{{ e.claim_status }}）</li></ul></td><td>{{ row.explanation }}</td></tr></tbody></table><ul><li v-for="note in report.report_json.uncertainties" :key="note">{{ note }}</li></ul></details>
  </section>
</template>
<style scoped>form,label{display:grid;gap:.5rem;margin:.7rem 0}select,button{font:inherit;padding:.5rem}table{border-collapse:collapse}th,td{padding:.6rem;border-bottom:1px solid #ddd}details{margin:1rem 0}[role=alert]{color:#b42318}</style>
