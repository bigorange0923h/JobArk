<script setup lang="ts">
/** 申请列表和事件时间线，合法目标由服务端返回。 */
import { onMounted, ref } from 'vue'
import { listApplications, fetchApplication, transitionApplication, statusLabels, type Application, type ApplicationDetail } from '@/shared/api/application'
import { listJobs, type JobListItem } from '@/shared/api/job'
import { fetchVersion, type ResumeVersion } from '@/shared/api/resume'
import { parseServerError } from '@/shared/forms/serverErrors'
const items = ref<Application[]>([])
const jobs = ref<JobListItem[]>([])
const selected = ref<ApplicationDetail | null>(null)
const resumeVersion = ref<ResumeVersion | null>(null)
const status = ref('')
const confirmed = ref(false)
const notes = ref('')
const error = ref('')
const busy = ref(false)
const columns = [
  { title: '职位', key: 'job' },
  { title: '申请尝试', dataIndex: 'attempt_no', key: 'attempt_no' },
  { title: '当前阶段', key: 'status' },
  { title: '操作', key: 'actions' },
]
async function load(): Promise<void> { try { [items.value, jobs.value] = await Promise.all([listApplications(), listJobs()]) } catch(e) { error.value = parseServerError(e).message } }
/** 查看绑定的历史版本，不读取简历的当前版本。 */
async function open(id: string): Promise<void> {
  if (busy.value) return
  busy.value = true; error.value = ''; resumeVersion.value = null
  try {
    selected.value = await fetchApplication(id)
    status.value = ''; confirmed.value = false; notes.value = ''
    resumeVersion.value = await fetchVersion(selected.value.resume_version_id)
  } catch(e) { error.value = parseServerError(e).message }
  finally { busy.value = false }
}
async function save(): Promise<void> {
  if (!selected.value || busy.value || !status.value || (status.value === 'APPLIED' && !confirmed.value)) return
  busy.value = true; error.value = ''
  try { selected.value = await transitionApplication(selected.value.id, { version: selected.value.version, status: status.value, confirm_applied: confirmed.value, notes: notes.value || null }); notes.value = ''; status.value = ''; confirmed.value = false; await load() }
  catch(e) { error.value = parseServerError(e).message }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <section class="application-view">
    <header class="page-header"><div><p class="page-eyebrow">APPLICATIONS</p><h1>申请记录</h1><p class="page-subtitle">每次申请和阶段变化都有独立记录。</p></div><a-button @click="load">刷新</a-button></header>
    <a-alert v-if="error" type="error" show-icon :message="error" class="section-gap" role="alert" />
    <a-card title="申请列表">
      <a-table :columns="columns" :data-source="items" row-key="id" :pagination="false" size="small">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'job'">{{ jobs.find(j => j.id === record.job_opportunity_id)?.title ?? record.job_opportunity_id }}</template>
          <template v-else-if="column.key === 'status'"><a-tag color="blue">{{ statusLabels[record.current_status] }}</a-tag></template>
          <template v-else-if="column.key === 'actions'"><a-button type="link" size="small" @click="open(record.id)">查看时间线</a-button></template>
        </template>
        <template #emptyText><a-empty description="暂无申请，请从职位详情选择简历版本创建。" /></template>
      </a-table>
    </a-card>
    <a-card v-if="selected" title="申请时间线" class="section-gap">
      <div class="detail-links"><RouterLink :to="`/jobs/${selected.job_opportunity_id}`">查看职位与 JD 历史</RouterLink><span>绑定简历版本：<RouterLink v-if="resumeVersion" :to="`/resumes/${resumeVersion.resume_id}/preview?version=${resumeVersion.id}`">预览当时的 v{{ resumeVersion.version_no }}</RouterLink><span v-else>{{ selected.resume_version_id }}</span></span></div>
      <a-timeline v-if="selected.events.length" class="event-list"><a-timeline-item v-for="event in selected.events" :key="event.id"><strong>{{ statusLabels[event.to_status] }}</strong><span class="event-time">{{ new Date(event.occurred_at).toLocaleString() }}</span><p v-if="event.notes">{{ event.notes }}</p></a-timeline-item></a-timeline>
      <a-empty v-else description="暂无阶段变化" />
      <a-divider />
      <a-form v-if="selected.allowed_statuses.length" layout="vertical" class="transition-form" @submit.prevent="save">
        <a-form-item label="下一阶段" required><a-select v-model:value="status" placeholder="请选择阶段" :options="selected.allowed_statuses.map(s => ({ value: s, label: statusLabels[s] }))" data-testid="next-status" /></a-form-item>
        <a-form-item label="备注"><a-textarea v-model:value="notes" :rows="3" :maxlength="10000" /></a-form-item>
        <a-form-item v-if="status === 'APPLIED'"><a-checkbox v-model:checked="confirmed" data-testid="confirm-applied">确认已在外部平台完成投递</a-checkbox></a-form-item>
        <a-button type="primary" :loading="busy" :disabled="!status || (status === 'APPLIED' && !confirmed)" data-testid="save-transition" @click="save">记录变更</a-button>
      </a-form>
      <a-alert v-else type="info" message="此申请已结束，重新申请请创建新的尝试。" />
    </a-card>
  </section>
</template>
<style scoped>
.detail-links { display: flex; flex-wrap: wrap; gap: 12px 24px; margin-bottom: 25px; color: var(--ja-color-muted); font-size: 13px; }
.event-list { padding: 0 5px; }
.event-time { margin-left: 12px; color: var(--ja-color-muted); font-size: 12px; }
.transition-form { max-width: 520px; }
</style>
