<script setup lang="ts">
/**
 * 工程状态页。
 *
 * 用途是验证"前端 → 开发代理 → 后端统一契约"这条链路是否打通：页面通过相对路径请求 `/health`，
 * 展示解包后的业务数据与请求标识。它不承载业务，阶段 1 出现真实页面后可移除。
 */

import { onMounted, ref } from 'vue'

import { ApiError } from '@/shared/api/client'
import { fetchHealth, type HealthPayload } from '@/shared/api/system'

const health = ref<HealthPayload | null>(null)
const errorMessage = ref<string | null>(null)
const errorRequestId = ref<string | null>(null)
const loading = ref(false)

/** 请求后端健康检查并更新页面状态。 */
async function check(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  errorRequestId.value = null

  try {
    health.value = await fetchHealth()
  } catch (error: unknown) {
    health.value = null
    if (error instanceof ApiError) {
      // 展示后端给出的安全提示；请求标识对应服务端日志，便于排查。
      errorMessage.value = error.message
      errorRequestId.value = error.requestId
    } else {
      errorMessage.value = '发生未知错误。'
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void check()
})
</script>

<template>
  <section class="status">
    <header class="page-header"><div><h1>工程状态</h1><p class="hint">验证前端代理与后端的连通情况。</p></div></header>
    <a-card title="后端服务">
      <a-spin v-if="loading" tip="检查中…" />
      <a-alert v-else-if="health" type="success" show-icon :message="`后端存活：${health.status}`" />
      <a-alert v-else type="error" show-icon :message="errorMessage ?? '连接失败'" :description="errorRequestId ? `错误编号：${errorRequestId}` : undefined" />
      <a-button class="retry-button" :loading="loading" @click="check">重新检查</a-button>
    </a-card>
  </section>
</template>

<style scoped>
.status {
  max-width: 32rem;
}

.hint {
  color: #6b7280;
}

.retry-button { margin-top: 18px; }
</style>
