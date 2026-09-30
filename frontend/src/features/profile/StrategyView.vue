<script setup lang="ts">
/**
 * 求职策略独立页：沿用 Profile 的单人偏好记录和保存接口，只改变页面归属。
 * 尚未建档时引导先创建；刷新或版本冲突时重新读取档案聚合，避免保存旧版本。
 */
import { onMounted, ref } from 'vue'

import { fetchProfile, type Profile } from '@/shared/api/profile'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import PreferencePanel from './components/PreferencePanel.vue'
import ExclusionRulesPanel from './components/ExclusionRulesPanel.vue'

const profile = ref<Profile | null>(null)
const notCreated = ref(false)
const loading = ref(false)
const loadError = ref<ParsedServerError | null>(null)
const conflictMessage = ref<string | null>(null)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    profile.value = await fetchProfile()
    notCreated.value = false
  } catch (error: unknown) {
    const parsed = parseServerError(error)
    profile.value = null
    if (parsed.code === 'RESOURCE_NOT_FOUND') {
      notCreated.value = true
    } else {
      notCreated.value = false
      loadError.value = parsed
    }
  } finally {
    loading.value = false
  }
}

function onConflict(message: string): void {
  conflictMessage.value = message
  void load()
}

onMounted(() => { void load() })
</script>

<template>
  <section class="strategy-view">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">STRATEGY</p>
        <h1>求职策略</h1>
        <p class="page-subtitle">管理求职偏好和当前职位的排除规则。</p>
      </div>
      <a-button size="small" :loading="loading" data-testid="reload-strategy" @click="load">刷新</a-button>
    </header>

    <a-alert
      type="info"
      show-icon
      class="strategy-notice"
      message="目标地点、薪资等偏好尚未用于职位匹配；下方结构化排除规则用于当前职位筛选。"
      data-testid="strategy-scope-notice"
    />
    <a-alert
      v-if="conflictMessage"
      type="warning"
      show-icon
      closable
      class="strategy-notice"
      message="求职偏好已被更新，已重新加载最新数据"
      :description="`${conflictMessage} 请基于最新数据重新提交。`"
      data-testid="strategy-conflict"
      @close="conflictMessage = null"
    />

    <a-spin v-if="loading && !profile" data-testid="strategy-loading" />
    <a-alert
      v-else-if="loadError"
      type="error"
      show-icon
      class="strategy-notice"
      :message="loadError.message"
      :description="[...loadError.general, loadError.requestId ? `错误编号：${loadError.requestId}` : ''].filter(Boolean).join(' ')"
      data-testid="strategy-load-error"
    >
      <template #action><a-button size="small" @click="load">重试</a-button></template>
    </a-alert>
    <a-card v-else-if="notCreated" :bordered="false" data-testid="strategy-needs-profile">
      <template #title>请先创建个人档案</template>
      <p>求职策略与当前个人档案关联。建档后即可在这里设置偏好。</p>
      <RouterLink :to="{ name: 'profile' }">前往个人资料</RouterLink>
    </a-card>
    <PreferencePanel
      v-else-if="profile"
      :preference="profile.preference"
      @changed="load"
      @conflict="onConflict"
    />
    <ExclusionRulesPanel v-if="profile" />
  </section>
</template>

<style scoped>
.strategy-notice { margin-bottom: 1rem; }
</style>
