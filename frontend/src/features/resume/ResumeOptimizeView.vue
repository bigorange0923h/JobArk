<script setup lang="ts">
/** AI 只提出已有条目选择方案；对比后仍需走原有候选稿确认流程。 */
import { computed, onMounted, ref } from 'vue'
import { requestV1 } from '@/shared/api/client'
import { listVersions, type ResumeVersion, type ResumeDraft } from '@/shared/api/resume'
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'
import ResumePreview from './components/ResumePreview.vue'
const props = defineProps<{ resumeId: string }>()
const versions = ref<ResumeVersion[]>([])
const baseId = ref('')
const target = ref('')
const consent = ref(false)
const draft = ref<ResumeDraft | null>(null)
/** 页面初始加载（读取基线版本）失败：留在页面上并保留重试入口。 */
const loadError = ref<ParsedServerError | null>(null)
/** 生成候选稿失败：生成是用户动作，无字段信息的失败走全局通知。 */
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

/** 读取可用的基线版本；失败时从页面内重试，不把页面替换成空态。 */
async function load(): Promise<void> {
  loadError.value = null
  try { versions.value = await listVersions(props.resumeId) }
  catch (error: unknown) { loadError.value = parseServerError(error) }
}

async function generate(): Promise<void> {
  if (busy.value || !baseId.value || !target.value.trim() || !consent.value) return
  busy.value = true; actionError.value = null
  try { draft.value = await requestV1(`/resumes/${props.resumeId}/optimize`, { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_resume_version_id: baseId.value, target: target.value, confirm_external: consent.value }) } }) }
  catch (error: unknown) { actionError.value = resolveActionFailure(error, '生成候选稿') }
  finally { busy.value = false }
}
onMounted(() => { void load() })
</script>
<template>
  <section class="resume-optimize-view">
    <header class="page-header"><div><p class="page-eyebrow">RESUME OPTIMIZATION</p><h1>AI 简历优化</h1><p class="page-subtitle">按目标筛选和重排已有条目，原始内容保持可追溯。</p></div></header>
    <a-alert type="info" show-icon message="只生成候选稿" description="不会新增技能、经历或成果；检查对比后再由你确认正式版本。" />
    <a-alert v-if="loadError" type="error" show-icon :message="loadError.message" :description="loadErrorDescription" class="section-gap" data-testid="load-error" role="alert"><template #action><a-button size="small" data-testid="retry-load" @click="load">重新加载</a-button></template></a-alert>
    <a-alert v-if="actionError" type="error" show-icon closable :message="actionError.message" :description="actionErrorDescription" class="section-gap" data-testid="action-error" role="alert" @close="actionError = null" />
    <a-card title="生成候选稿" class="section-gap">
      <a-form layout="vertical" @submit.prevent="generate">
        <a-form-item label="基线版本" required><a-select v-model:value="baseId" :disabled="busy" placeholder="选择正式版本" :options="versions.map(v => ({ value: v.id, label: `版本 ${v.version_no}` }))" data-testid="base-version" /></a-form-item>
        <a-form-item label="目标方向" required><a-textarea v-model:value="target" :rows="4" :maxlength="2000" placeholder="说明目标职位或侧重点" data-testid="target-direction" /></a-form-item>
        <a-form-item><a-checkbox v-model:checked="consent" data-testid="gateway-consent">确认发送目标方向和简历条目到已配置的大模型服务；条目自由文本可能包含个人信息</a-checkbox></a-form-item>
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
