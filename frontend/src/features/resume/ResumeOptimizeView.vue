<script setup lang="ts">
/** AI 只提出已有条目选择方案；对比后仍需走原有候选稿确认流程。 */
import { onMounted, ref } from 'vue'
import { requestV1 } from '@/shared/api/client'
import { listVersions, type ResumeVersion, type ResumeDraft } from '@/shared/api/resume'
import { parseServerError } from '@/shared/forms/serverErrors'
import ResumePreview from './components/ResumePreview.vue'
const props = defineProps<{ resumeId: string }>()
const versions = ref<ResumeVersion[]>([])
const baseId = ref('')
const target = ref('')
const consent = ref(false)
const draft = ref<ResumeDraft | null>(null)
const error = ref('')
const busy = ref(false)
async function generate(): Promise<void> {
  if (busy.value || !baseId.value || !target.value.trim() || !consent.value) return
  busy.value = true; error.value = ''
  try { draft.value = await requestV1(`/resumes/${props.resumeId}/optimize`, { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_resume_version_id: baseId.value, target: target.value, confirm_external: consent.value }) } }) }
  catch(e) { error.value = parseServerError(e).message }
  finally { busy.value = false }
}
onMounted(async () => { try { versions.value = await listVersions(props.resumeId) } catch(e) { error.value = parseServerError(e).message } })
</script>
<template>
  <section class="resume-optimize-view">
    <header class="page-header"><div><p class="page-eyebrow">RESUME OPTIMIZATION</p><h1>AI 简历优化</h1><p class="page-subtitle">按目标筛选和重排已有条目，原始内容保持可追溯。</p></div></header>
    <a-alert type="info" show-icon message="只生成候选稿" description="不会新增技能、经历或成果；检查对比后再由你确认正式版本。" />
    <a-alert v-if="error" type="error" show-icon :message="error" class="section-gap" role="alert" />
    <a-card title="生成候选稿" class="section-gap">
      <a-form layout="vertical" @submit.prevent="generate">
        <a-form-item label="基线版本" required><a-select v-model:value="baseId" :disabled="busy" placeholder="选择正式版本" :options="versions.map(v => ({ value: v.id, label: `版本 ${v.version_no}` }))" data-testid="base-version" /></a-form-item>
        <a-form-item label="目标方向" required><a-textarea v-model:value="target" :rows="4" :maxlength="2000" placeholder="说明目标职位或侧重点" data-testid="target-direction" /></a-form-item>
        <a-form-item><a-checkbox v-model:checked="consent" data-testid="gateway-consent">确认发送目标方向和简历条目到已配置的 AI 网关；条目自由文本可能包含个人信息</a-checkbox></a-form-item>
        <a-button type="primary" :loading="busy" :disabled="!consent || !baseId || !target.trim()" data-testid="generate-draft" @click="generate">生成候选稿</a-button>
      </a-form>
    </a-card>
    <a-card v-if="draft" title="确认前对比" class="section-gap">
      <p class="card-hint">检查条目是否遗漏、顺序是否符合目标；此候选尚未成为正式版本。</p>
      <div class="comparison"><article><h3>原版本</h3><template v-for="version in versions.filter(v => v.id === draft?.base_resume_version_id)" :key="version.id"><ResumePreview :document="version.document_json" /></template></article><article><h3>候选稿</h3><ResumePreview :document="draft.document_json" /></article></div>
      <a-space class="next-actions"><RouterLink :to="`/resumes/${resumeId}/drafts/${draft.id}`">继续编辑候选稿</RouterLink><RouterLink :to="`/resumes/${resumeId}`">返回简历详情确认或丢弃</RouterLink></a-space>
    </a-card>
  </section>
</template>
<style scoped>
.resume-optimize-view > .ant-card:first-of-type { max-width: 780px; }
.comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--ja-space-section); }
.comparison article { min-width: 0; overflow-x: auto; }
.comparison h3 { margin: 0 0 14px; color: var(--ja-color-text); font-size: 15px; }
.next-actions { margin-top: 20px; }
@media (max-width: 1050px) { .comparison { grid-template-columns: 1fr; } }
</style>
