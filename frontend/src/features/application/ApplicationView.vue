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
  if (!selected.value || busy.value) return
  busy.value = true; error.value = ''
  try { selected.value = await transitionApplication(selected.value.id, { version: selected.value.version, status: status.value, confirm_applied: confirmed.value, notes: notes.value || null }); notes.value = ''; status.value = ''; confirmed.value = false; await load() }
  catch(e) { error.value = parseServerError(e).message }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <section><h1>申请记录</h1><button @click="load">刷新</button><p v-if="error" role="alert">{{ error }}</p><p v-if="!items.length">暂无申请，请从职位详情选择简历版本创建。</p>
    <table v-else><thead><tr><th>职位</th><th>尝试</th><th>阶段</th><th>操作</th></tr></thead><tbody><tr v-for="item in items" :key="item.id"><td>{{ jobs.find(j => j.id === item.job_opportunity_id)?.title ?? item.job_opportunity_id }}</td><td>{{ item.attempt_no }}</td><td>{{ statusLabels[item.current_status] }}</td><td><button @click="open(item.id)">查看时间线</button></td></tr></tbody></table>
    <article v-if="selected"><h2>申请时间线</h2><RouterLink :to="`/jobs/${selected.job_opportunity_id}`">查看职位与 JD 历史</RouterLink><p>绑定简历版本：<RouterLink v-if="resumeVersion" :to="`/resumes/${resumeVersion.resume_id}/preview?version=${resumeVersion.id}`">预览当时的 v{{ resumeVersion.version_no }}</RouterLink><span v-else>{{ selected.resume_version_id }}</span></p><ol><li v-for="event in selected.events" :key="event.id">{{ new Date(event.occurred_at).toLocaleString() }} · {{ statusLabels[event.to_status] }} {{ event.notes }}</li></ol>
      <form v-if="selected.allowed_statuses.length" @submit.prevent="save"><label>下一阶段 <select v-model="status" required><option value="" disabled>请选择</option><option v-for="s in selected.allowed_statuses" :key="s" :value="s">{{ statusLabels[s] }}</option></select></label><label>备注 <textarea v-model="notes" maxlength="10000" /></label><label v-if="status === 'APPLIED'"><input v-model="confirmed" type="checkbox" required>确认已在外部平台完成投递</label><button :disabled="busy || !status">记录变更</button></form><p v-else>此申请已结束，重新申请请创建新的尝试。</p>
    </article>
  </section>
</template>
<style scoped>
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.7rem;border-bottom:1px solid #ddd}form,label{display:grid;gap:.7rem;margin:.7rem 0}input,select,textarea,button{font:inherit;padding:.5rem}button{width:fit-content}[role=alert]{color:#b42318}
</style>
