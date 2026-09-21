<script setup lang="ts">
/**
 * 资料修订面板。
 *
 * 修订是"当时事实的不可变快照"：简历版本与匹配结果都引用它，因此它不是版本管理的形式主义，
 * 而是"匹配与简历可复现"的实现基础（见 `docs/data-model.md` 3.4）。
 *
 * 它不在每次编辑时创建——那会让修订表被输入框的中间状态淹没——所以这里只在用户显式点击时创建，
 * 并且要把后果说清楚：**修订一旦引用某条事实，那条事实就不能再删除**（后端返回 409）。
 * 这正是这个面板存在的主要价值：让"为什么删不掉"有可见的前因。
 *
 * 本面板自行加载数据：修订不属于 `GET /profile` 聚合返回的内容。
 */

import { onMounted, ref } from 'vue'

import { createRevision, listRevisions, type Revision } from '@/shared/api/profile'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

const revisions = ref<Revision[]>([])
const reason = ref('')
const loading = ref(false)
const creating = ref(false)
const error = ref<ParsedServerError | null>(null)

const columns = [
  { title: '修订号', key: 'revision_no', dataIndex: 'revision_no' },
  { title: '原因', key: 'reason', dataIndex: 'reason' },
  { title: '创建时间', key: 'created_at', dataIndex: 'created_at' },
]

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    revisions.value = await listRevisions()
  } catch (caught: unknown) {
    error.value = parseServerError(caught)
  } finally {
    loading.value = false
  }
}

async function create(): Promise<void> {
  const trimmed = reason.value.trim()
  if (trimmed === '') {
    error.value = {
      code: 'VALIDATION_ERROR',
      message: '请填写创建修订的原因。',
      fields: {},
      general: ['原因是修订记录的一部分：将来回看时必须能解释这次快照为什么存在。'],
      requestId: null,
    }
    return
  }

  creating.value = true
  error.value = null
  try {
    await createRevision(trimmed)
    reason.value = ''
    await load()
  } catch (caught: unknown) {
    error.value = parseServerError(caught)
  } finally {
    creating.value = false
  }
}

/** 表格插槽把行数据声明为任意类型，断言收敛在此。 */
function formatRowTime(record: unknown): string {
  const value = (record as Revision).created_at
  return typeof value === 'string' ? new Date(value).toLocaleString() : '—'
}

onMounted(() => {
  void load()
})
</script>

<template>
  <a-card :bordered="false" class="revision-panel" data-testid="panel-revisions">
    <template #title>资料修订</template>
    <template #extra>
      <a-button size="small" :loading="loading" @click="load">刷新</a-button>
    </template>

    <p class="panel-description">
      修订是当前事实的不可变快照，用于让"简历版本与匹配结果"可复现。只在你确实要生成简历、
      发起匹配或确认重要变更时创建。注意：被修订引用的事实将无法再删除（会返回冲突提示）。
    </p>

    <a-alert
      v-if="error"
      type="error"
      show-icon
      class="panel-alert"
      :message="error.message"
      :description="error.general.join(' ')"
      data-testid="error-revisions"
    />

    <a-space class="create-row">
      <a-input
        :value="reason"
        :maxlength="200"
        placeholder="创建原因，例如：生成投递简历"
        class="reason-input"
        @update:value="(value: unknown) => (reason = String(value))"
        @press-enter="create"
      />
      <a-button type="primary" :loading="creating" data-testid="create-revision" @click="create">创建修订</a-button>
    </a-space>

    <a-table
      :data-source="revisions"
      :columns="columns"
      :pagination="false"
      row-key="id"
      size="small"
      :locale="{ emptyText: '暂无修订' }"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'created_at'">{{ formatRowTime(record) }}</template>
      </template>
    </a-table>
  </a-card>
</template>

<style scoped>
.revision-panel {
  margin-bottom: 1rem;
}

.panel-description {
  color: #6b7280;
  margin-bottom: 0.75rem;
}

.panel-alert {
  margin-bottom: 1rem;
}

.create-row {
  margin-bottom: 0.75rem;
}

.reason-input {
  width: 20rem;
}
</style>
