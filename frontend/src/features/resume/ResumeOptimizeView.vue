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
  if (busy.value) return
  busy.value = true; error.value = ''
  try { draft.value = await requestV1(`/resumes/${props.resumeId}/optimize`, { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_resume_version_id: baseId.value, target: target.value, confirm_external: consent.value }) } }) }
  catch(e) { error.value = parseServerError(e).message }
  finally { busy.value = false }
}
onMounted(async () => { try { versions.value = await listVersions(props.resumeId) } catch(e) { error.value = parseServerError(e).message } })
</script>
<template>
  <section><h1>AI 简历优化</h1><p>按目标筛选和重排已有条目。保留原文，不生成新的技能、经历或成果。</p><p v-if="error" role="alert">{{ error }}</p>
    <form @submit.prevent="generate"><label>基线 <select v-model="baseId" required :disabled="busy"><option v-for="v in versions" :key="v.id" :value="v.id">版本 {{ v.version_no }}</option></select></label><label>目标方向 <textarea v-model="target" required maxlength="2000" /></label><label><input v-model="consent" type="checkbox" required>确认发送目标方向和简历条目到已配置的 AI 网关；条目自由文本可能包含个人信息</label><button :disabled="busy || !consent || !baseId">生成候选稿</button></form>
    <template v-if="draft"><h2>确认前对比</h2><p>检查条目是否被遗漏、顺序是否符合目标；此候选尚未成为正式版本。</p><div class="comparison"><article><h3>原版本</h3><template v-for="version in versions.filter(v => v.id === draft?.base_resume_version_id)" :key="version.id"><ResumePreview :document="version.document_json" /></template></article><article><h3>候选稿</h3><ResumePreview :document="draft.document_json" /></article></div><RouterLink :to="`/resumes/${resumeId}/drafts/${draft.id}`">继续编辑候选稿</RouterLink> · <RouterLink :to="`/resumes/${resumeId}`">返回简历详情确认或丢弃</RouterLink></template>
  </section>
</template>
<style scoped>form,label{display:grid;gap:.7rem;margin:.7rem 0}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:1rem}article{min-width:0;overflow:auto}select,textarea,button{font:inherit;padding:.5rem}[role=alert]{color:#b42318}@media(max-width:900px){.comparison{grid-template-columns:1fr}}</style>
