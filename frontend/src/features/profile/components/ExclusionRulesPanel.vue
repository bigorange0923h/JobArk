<script setup lang="ts">
/** 四类规则单独维护；预览只读取服务端判定，不在浏览器自行裁决。 */
import { onMounted, ref } from 'vue'
import { getExclusionPolicy, saveExclusionPolicy, listJobs, previewExclusion, type ExclusionKind, type ExclusionPolicy, type ExclusionRule } from '@/shared/api/job'
import { parseServerError } from '@/shared/forms/serverErrors'

const groups: { kind: ExclusionKind; title: string; help: string; options?: { value: string; label: string }[] }[] = [
  { kind: 'COMPANY_NATURE', title: '公司性质', help: '外包相关同时检查已确认的公司性质和当前岗位安排。', options: [
    { value: 'OUTSOURCING_RELATED', label: '外包相关（含单个外包岗位）' }, { value: 'OUTSOURCING_PROVIDER', label: '外包服务商' },
    { value: 'LABOR_DISPATCH', label: '人力派遣' },
  ] },
  { kind: 'COMPANY_INDUSTRY', title: '公司行业', help: '父级覆盖明确归属的子类；旧行业文本需另行核对。', options: [
    { value: 'TECH', label: '科技' }, { value: 'TECH/SOFTWARE', label: '科技 / 软件' }, { value: 'TECH/HARDWARE', label: '科技 / 硬件' }, { value: 'TECH/INTERNET', label: '科技 / 互联网' },
    { value: 'FINANCE', label: '金融' }, { value: 'FINANCE/BANKING', label: '金融 / 银行' }, { value: 'FINANCE/INSURANCE', label: '金融 / 保险' }, { value: 'FINANCE/SECURITIES', label: '金融 / 证券' },
    { value: 'MANUFACTURING', label: '制造' }, { value: 'MANUFACTURING/ELECTRONICS', label: '制造 / 电子' }, { value: 'MANUFACTURING/OTHER', label: '制造 / 其他' },
    { value: 'SERVICES', label: '服务' }, { value: 'SERVICES/HR', label: '服务 / 人力资源' }, { value: 'SERVICES/CONSULTING', label: '服务 / 咨询' },
  ] },
  { kind: 'COMPANY_NAME', title: '公司名称', help: '完整名称匹配；同名公司可能同时命中，别名需逐项添加。' },
  { kind: 'JD_KEYWORD', title: 'JD 关键词', help: '明确字面命中排除；“非外包”等语境待核对。' },
]
const policy = ref<ExclusionPolicy>({ version: 0, rules: [] })
const values = ref<Record<ExclusionKind, string>>({ COMPANY_NATURE: '', COMPANY_INDUSTRY: '', COMPANY_NAME: '', JD_KEYWORD: '' })
const loading = ref(true)
const saving = ref(false)
const message = ref('')
const error = ref('')
const previewJob = ref('')
const jobOptions = ref<{ value: string; label: string }[]>([])
const previewText = ref('')

async function load(): Promise<void> {
  loading.value = true; error.value = ''
  try {
    policy.value = await getExclusionPolicy()
    jobOptions.value = (await listJobs()).map(job => ({ value: job.id, label: `${job.company_name} · ${job.title}` }))
  } catch (cause) { error.value = parseServerError(cause).message }
  finally { loading.value = false }
}
function add(kind: ExclusionKind): void {
  const value = values.value[kind].trim()
  if (!value || policy.value.rules.some(rule => rule.kind === kind && rule.value.toLowerCase() === value.toLowerCase())) return
  policy.value.rules.push({ id: crypto.randomUUID(), kind, value, enabled: true })
  values.value[kind] = ''
  message.value = '规则尚未保存'
}
function remove(id: string): void { policy.value.rules = policy.value.rules.filter(rule => rule.id !== id); message.value = '规则尚未保存' }
async function save(): Promise<void> {
  saving.value = true; error.value = ''; message.value = ''
  try { policy.value = await saveExclusionPolicy(policy.value); message.value = '规则已保存并用于当前职位判定' }
  catch (cause) { error.value = parseServerError(cause).message }
  finally { saving.value = false }
}
async function preview(): Promise<void> {
  if (!previewJob.value) return
  try {
    const result = await previewExclusion(previewJob.value)
    previewText.value = `${result.decision.verdict}：${result.decision.reasons.map(reason => `${reason.text}${reason.snippet ? `（${reason.snippet}）` : ''}`).join('；') || '无命中'}`
  } catch (cause) { previewText.value = `预览失败：${parseServerError(cause).message}` }
}
onMounted(load)
</script>

<template>
  <a-card title="结构化排除规则" class="section-gap">
    <a-spin v-if="loading" />
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <a-alert v-if="message" type="info" show-icon :message="message" />
    <template v-if="!loading">
      <div v-for="group in groups" :key="group.kind" class="rule-group">
        <h3>{{ group.title }}</h3><p>{{ group.help }}</p>
        <div class="rule-entry">
          <a-select v-if="group.options" v-model:value="values[group.kind]" :options="group.options" placeholder="选择分类" class="rule-input" />
          <a-input v-else v-model:value="values[group.kind]" :maxlength="200" placeholder="输入完整名称或关键词" class="rule-input" @press-enter="add(group.kind)" />
          <a-button :data-testid="`add-rule-${group.kind}`" @click="add(group.kind)">添加</a-button>
        </div>
        <div v-for="rule in policy.rules.filter((item: ExclusionRule) => item.kind === group.kind)" :key="rule.id" class="rule-row">
          <a-switch v-model:checked="rule.enabled" :aria-label="`启用 ${rule.value}`" @change="message = '规则尚未保存'" />
          <span>{{ group.options?.find(option => option.value === rule.value)?.label ?? rule.value }}</span>
          <a-button size="small" danger @click="remove(rule.id)">删除</a-button>
        </div>
      </div>
      <a-button type="primary" :loading="saving" data-testid="save-exclusion-rules" @click="save">保存排除规则</a-button>
      <div class="rule-entry preview-entry">
        <a-select v-model:value="previewJob" :options="jobOptions" placeholder="选择现有职位预览" class="rule-input" show-search option-filter-prop="label" />
        <a-button @click="preview">预览判定</a-button>
      </div>
      <p v-if="previewText">{{ previewText }}</p>
    </template>
  </a-card>
</template>

<style scoped>
.rule-group { border-top: 1px solid var(--ja-border-color, #eee); padding: .75rem 0; }
.rule-group h3 { margin: 0; }
.rule-group p { color: #6b7280; margin: .25rem 0 .5rem; }
.rule-entry, .rule-row { display: flex; gap: .5rem; align-items: center; margin: .5rem 0; }
.rule-input { max-width: 28rem; min-width: 14rem; }
.preview-entry { margin-top: 1rem; }
</style>
