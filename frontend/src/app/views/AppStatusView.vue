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
    <h1>工程状态</h1>
    <p class="hint">本页用于验证前端、开发代理与后端契约是否已打通。</p>

    <p v-if="loading" class="pending">检查中…</p>
    <p v-else-if="health" class="ok">后端存活：{{ health.status }}</p>
    <div v-else class="failed">
      <p>{{ errorMessage }}</p>
      <p v-if="errorRequestId" class="request-id">错误编号：{{ errorRequestId }}</p>
    </div>

    <button type="button" :disabled="loading" @click="check">重新检查</button>
  </section>
</template>

<style scoped>
.status {
  max-width: 32rem;
}

.hint {
  color: #6b7280;
}

.ok {
  color: #15803d;
}

.failed {
  color: #b91c1c;
}

.request-id {
  font-family: ui-monospace, 'Cascadia Mono', monospace;
  color: #6b7280;
}

button {
  padding: 0.4rem 1rem;
}
</style>
