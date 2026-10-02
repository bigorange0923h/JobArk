<script setup lang="ts">
/** 申请列表和事件时间线，合法目标由服务端返回。 */
import { computed, onMounted, ref } from 'vue'
import { listApplications, fetchApplication, transitionApplication, changeApplicationMaterials, statusLabels, type Application, type ApplicationDetail } from '@/shared/api/application'
import { listJobs, listSnapshots, type JobSnapshot, type JobListItem } from '@/shared/api/job'
import { fetchVersion, listResumes, listVersions, type ResumeVersion } from '@/shared/api/resume'
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'
const items = ref<Application[]>([])
const jobs = ref<JobListItem[]>([])
const selected = ref<ApplicationDetail | null>(null)
const resumeVersion = ref<ResumeVersion | null>(null)
const status = ref('')
const snapshots = ref<JobSnapshot[]>([])
const versions = ref<ResumeVersion[]>([])
const snapshotId = ref('')
const versionId = ref<string | null>(null)
/** 标记已投递前必须在二次弹窗确认，取消不改变当前表单。 */
const confirmAppliedOpen = ref(false)
const notes = ref('')
/** 页面初始加载失败：留在页面上并保留重试入口，不用会自动消失的通知替代。 */
const loadError = ref<ParsedServerError | null>(null)
/** 用户操作失败：只有需要字段或操作上下文的原因才内联展示，其余走全局通知。 */
const actionError = ref<ParsedServerError | null>(null)
const busy = ref(false)

/** 把解析后的错误拼成"补充原因 + 错误编号"的说明文本。 */
function describeError(error: ParsedServerError | null): string | undefined {
  if (error === null) return undefined
  const parts = [...error.general]
  if (error.requestId !== null) parts.push(`错误编号：${error.requestId}`)
  return parts.length === 0 ? undefined : parts.join(' ')
}

const loadErrorDescription = computed(() => describeError(loadError.value))
const actionErrorDescription = computed(() => describeError(actionError.value))

const columns = [
  { title: '职位', key: 'job' },
  { title: '申请尝试', dataIndex: 'attempt_no', key: 'attempt_no' },
  { title: '当前阶段', key: 'status' },
  { title: '操作', key: 'actions' },
]
async function load(): Promise<void> {
  loadError.value = null
  try { [items.value, jobs.value] = await Promise.all([listApplications(), listJobs()]) }
  catch (error: unknown) { loadError.value = parseServerError(error) }
}
/** 查看绑定的历史版本，不读取简历的当前版本。 */
async function open(id: string): Promise<void> {
  if (busy.value) return
  busy.value = true; actionError.value = null; resumeVersion.value = null
  try {
    selected.value = await fetchApplication(id)
    status.value = ''; confirmAppliedOpen.value = false; notes.value = ''
    if (selected.value.resume_version_id) resumeVersion.value = await fetchVersion(selected.value.resume_version_id)
    snapshotId.value = selected.value.job_snapshot_id; versionId.value = selected.value.resume_version_id
    snapshots.value = await listSnapshots(selected.value.job_opportunity_id)
    const resumes = await listResumes()
    versions.value = (await Promise.all(resumes.map(resume => listVersions(resume.id)))).flat()
  } catch (error: unknown) { actionError.value = resolveActionFailure(error, '读取申请时间线') }
  finally { busy.value = false }
}
async function save(confirmApplied = false): Promise<void> {
  if (!selected.value || busy.value || !status.value) return
  if (status.value === 'APPLIED' && !confirmApplied) {
    confirmAppliedOpen.value = true
    return
  }
  busy.value = true; actionError.value = null
  // 版本冲突（409）会原样返回并内联展示：用户需要在原备注与阶段选择上重试，而不是丢掉已填内容。
  try { selected.value = await transitionApplication(selected.value.id, { version: selected.value.version, status: status.value, confirm_applied: confirmApplied, notes: notes.value || null }); notes.value = ''; status.value = ''; confirmAppliedOpen.value = false; await load() }
  catch (error: unknown) { actionError.value = resolveActionFailure(error, '记录申请变更') }
  finally { busy.value = false }
}
/** 保存准备材料后采用服务端时间线与版本；失败保留选择。 */
async function saveMaterials(): Promise<void> {
  if (!selected.value || busy.value) return
  busy.value = true; actionError.value = null
  try {
    selected.value = await changeApplicationMaterials(selected.value.id, { version: selected.value.version, job_snapshot_id: snapshotId.value, resume_version_id: versionId.value ?? null })
    resumeVersion.value = selected.value.resume_version_id ? await fetchVersion(selected.value.resume_version_id) : null
    await load()
  } catch (error: unknown) { actionError.value = resolveActionFailure(error, '更换申请材料') }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <section class="application-view">
    <header class="page-header"><div><p class="page-eyebrow">APPLICATIONS</p><h1>申请记录</h1><p class="page-subtitle">每次申请和阶段变化都有独立记录。</p></div><a-button data-testid="reload" @click="load">刷新</a-button></header>
    <a-alert v-if="loadError" type="error" show-icon :message="loadError.message" :description="loadErrorDescription" class="section-gap" data-testid="load-error" role="alert">
      <template #action><a-button size="small" data-testid="retry-load" @click="load">重新加载</a-button></template>
    </a-alert>
    <a-alert v-if="actionError" type="error" show-icon closable :message="actionError.message" :description="actionErrorDescription" class="section-gap" data-testid="action-error" role="alert" @close="actionError = null" />
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
      <div class="detail-links"><RouterLink :to="`/jobs/${selected.job_opportunity_id}`">查看职位与 JD 历史</RouterLink><span>绑定简历版本：<RouterLink v-if="resumeVersion" :to="`/resumes/${resumeVersion.resume_id}/preview?version=${resumeVersion.id}`">预览当时的 v{{ resumeVersion.version_no }}</RouterLink><span v-else>{{ selected.resume_version_id ?? '尚未选择' }}</span></span></div>
      <a-alert v-if="selected.material_locked_at" type="info" message="首次投递时的材料已永久锁定；再次申请请创建新的尝试。" />
      <a-form v-else-if="['SAVED', 'PREPARING', 'READY_TO_APPLY'].includes(selected.current_status)" layout="vertical" class="transition-form">
        <a-form-item label="申请 JD"><a-select v-model:value="snapshotId" :options="snapshots.map(item => ({ value: item.id, label: new Date(item.captured_at).toLocaleString() + ' · ' + item.raw_jd.slice(0, 40) }))" /></a-form-item>
        <a-form-item label="简历版本（准备阶段可暂不选择）"><a-select v-model:value="versionId" allow-clear :options="versions.map(item => ({ value: item.id, label: 'v' + item.version_no + ' · ' + item.created_reason }))" /></a-form-item>
        <a-button :loading="busy" @click="saveMaterials">保存材料</a-button>
        <p>待投递阶段更换材料后会回到准备中，需要重新检查。</p>
      </a-form>
      <a-timeline v-if="selected.events.length" class="event-list"><a-timeline-item v-for="event in selected.events" :key="event.id"><strong>{{ event.event_type === 'MATERIALS_CHANGED' ? '材料已更换' : statusLabels[event.to_status] }}</strong><span class="event-time">{{ new Date(event.occurred_at).toLocaleString() }}</span><p v-if="event.notes">{{ event.notes }}</p></a-timeline-item></a-timeline>
      <a-empty v-else description="暂无阶段变化" />
      <a-divider />
      <a-form v-if="selected.allowed_statuses.length" layout="vertical" class="transition-form" @submit.prevent="save()">
        <a-form-item label="下一阶段" required><a-select v-model:value="status" placeholder="请选择阶段" :options="selected.allowed_statuses.map(s => ({ value: s, label: statusLabels[s] }))" data-testid="next-status" /></a-form-item>
        <a-form-item label="备注"><a-textarea v-model:value="notes" :rows="3" :maxlength="10000" /></a-form-item>
        <a-button type="primary" :loading="busy" :disabled="!status" data-testid="save-transition" @click="save()">记录变更</a-button>
      </a-form>
      <a-alert v-else type="info" message="此申请已结束，重新申请请创建新的尝试。" />
      <a-modal v-if="confirmAppliedOpen" :open="confirmAppliedOpen" title="确认记录为已投递" :confirm-loading="busy" ok-text="确认已完成投递" cancel-text="取消" @ok="save(true)" @cancel="confirmAppliedOpen = false">
        <div data-testid="confirm-applied-dialog">
          <p>系统将记录你已在外部平台完成投递，并锁定当前 JD 与简历版本。</p><p>JD：{{ selected.job_snapshot_id }}<br />简历：{{ resumeVersion ? 'v' + resumeVersion.version_no : '尚未选择' }}</p>
          <p class="confirm-hint">此操作不会代你投递，也不会向招聘平台发送任何内容。</p>
          <a-alert v-if="actionError" type="error" show-icon :message="actionError.message" :description="actionErrorDescription" class="confirm-error" />
        </div>
      </a-modal>
    </a-card>
  </section>
</template>
<style scoped>
.detail-links { display: flex; flex-wrap: wrap; gap: 12px 24px; margin-bottom: 25px; color: var(--ja-color-muted); font-size: 13px; }
.event-list { padding: 0 5px; }
.event-time { margin-left: 12px; color: var(--ja-color-muted); font-size: 12px; }
.transition-form { max-width: 520px; }
.confirm-hint { color: var(--ja-color-muted); font-size: 13px; line-height: 1.6; }
.confirm-error { margin-top: 12px; }
</style>
