<script setup lang="ts">
/** 归档内容单独恢复，历史引用与旧技能名称冲突由服务端校验。 */
import { onMounted, ref } from 'vue'
import { fetchArchivedFacts, restoreArchivedFact, type ArchivedFacts, type ArchivedFactKind, type ArchivedFact } from '@/shared/api/profile'
import { resolveActionFailure } from '@/shared/feedback/failureNotice'
import { parseServerError } from '@/shared/forms/serverErrors'
const emit = defineEmits<{ changed: [] }>()
const facts = ref<ArchivedFacts | null>(null)
const error = ref<string | null>(null)
const busy = ref(false)
const labels: Record<ArchivedFactKind, string> = { skills: '技能', experiences: '工作经历', projects: '项目', educations: '教育', languages: '语言' }
/** 显式加载已归档项，默认档案列表保持简洁。 */
async function load(): Promise<void> {
  error.value = null
  try { facts.value = await fetchArchivedFacts() }
  catch (cause: unknown) { error.value = parseServerError(cause).message }
}
/** 恢复成功后刷新当前档案；冲突保留归档项以便用户处理。 */
async function restore(kind: ArchivedFactKind, item: ArchivedFact): Promise<void> {
  if (busy.value) return
  busy.value = true; error.value = null
  try { await restoreArchivedFact(kind, item.id, item.version); await load(); emit('changed') }
  catch (cause: unknown) { error.value = resolveActionFailure(cause, '恢复归档内容')?.message ?? null }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <a-card size="small" title="已归档资料">
    <template #extra><a-button size="small" @click="load">刷新归档列表</a-button></template>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <template v-if="facts">
      <div v-for="(label, kind) in labels" :key="kind">
        <a-list v-if="facts[kind].length" :header="label" :data-source="facts[kind]" size="small">
          <template #renderItem="{ item }"><a-list-item>
            {{ item.name ?? item.company ?? item.school ?? item.language }}{{ item.title ? ' · ' + item.title : '' }}
            <template #actions><a-button type="link" :loading="busy" @click="restore(kind, item)">恢复</a-button></template>
          </a-list-item></template>
        </a-list>
      </div>
      <a-empty v-if="Object.values(facts).every(items => items.length === 0)" description="暂无归档内容" />
    </template>
  </a-card>
</template>
