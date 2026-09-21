<script setup lang="ts">
/**
 * 求职偏好面板。
 *
 * 偏好是**可变规则**而不是履历事实：它整体替换（未提交的字段按清空处理），已存在时必须提交
 * 当前版本号，首次创建则不带版本号——这两种情况由后端分别校验，前端只如实传递。
 *
 * 数据来源是档案聚合里的 `preference`，不额外请求 `GET /profile/preference`：聚合已经给出
 * "是否存在偏好"，再请求一次只会多一次往返和一处可能与聚合不一致的状态。
 *
 * 金额区间的大小关系不在前端校验：那是后端的裁决，前端复制一份会出现两套规则逐渐不一致；
 * 提交非法区间会得到带 `salary_max` 字段的 422，直接显示在对应字段下。
 */

import { computed, ref, watch } from 'vue'

import { savePreference, type Preference, type PreferenceInput, type RemotePreference } from '@/shared/api/profile'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import { REMOTE_PREFERENCE_LABELS } from '../descriptors'
import type { FieldOption } from '../types'

const props = defineProps<{
  /** 当前偏好；为 null 表示尚未设置。 */
  preference: Preference | null
}>()

const emit = defineEmits<{
  /** 保存成功，页面应重新加载档案聚合。 */
  changed: []
  /** 版本过期等需要刷新才能继续的冲突。 */
  conflict: [message: string]
}>()

const targetLocations = ref<string[]>([])
const jobTypes = ref<string[]>([])
const salaryMin = ref<number | null>(null)
const salaryMax = ref<number | null>(null)
const salaryCurrency = ref('')
const remotePreference = ref<string | null>(null)
const exclusions = ref<string[]>([])
const fieldErrors = ref<Record<string, string>>({})
const panelError = ref<ParsedServerError | null>(null)
const saving = ref(false)

const remoteOptions: FieldOption[] = Object.entries(REMOTE_PREFERENCE_LABELS).map(([value, label]) => ({ value, label }))

const isCreate = computed(() => props.preference === null)

const alertDescription = computed(() => {
  if (panelError.value === null) {
    return undefined
  }
  const parts = [...panelError.value.general]
  if (panelError.value.requestId !== null) {
    parts.push(`错误编号：${panelError.value.requestId}`)
  }
  return parts.length === 0 ? undefined : parts.join(' ')
})

watch(
  () => props.preference,
  (preference) => {
    targetLocations.value = preference?.target_locations ?? []
    jobTypes.value = preference?.job_types ?? []
    salaryMin.value = preference?.salary_min ?? null
    salaryMax.value = preference?.salary_max ?? null
    salaryCurrency.value = preference?.salary_currency ?? ''
    remotePreference.value = preference?.remote_preference ?? null
    exclusions.value = preference?.exclusions ?? []
    fieldErrors.value = {}
    panelError.value = null
  },
  { immediate: true },
)

async function submit(): Promise<void> {
  fieldErrors.value = {}
  panelError.value = null
  saving.value = true
  try {
    const payload: PreferenceInput = {
      target_locations: targetLocations.value,
      job_types: jobTypes.value,
      salary_min: salaryMin.value,
      salary_max: salaryMax.value,
      salary_currency: salaryCurrency.value.trim() === '' ? null : salaryCurrency.value.trim(),
      remote_preference: (remotePreference.value as RemotePreference | null) ?? null,
      exclusions: exclusions.value,
    }
    // 已存在时必须带版本号；首次创建时带上会被后端拒绝（避免"以为在更新其实在创建"）。
    if (props.preference !== null) {
      payload.version = props.preference.version
    }
    await savePreference(payload)
    emit('changed')
  } catch (error: unknown) {
    const parsed = parseServerError(error)
    fieldErrors.value = parsed.fields
    panelError.value = parsed
    if (parsed.code === 'CONFLICT' && parsed.fields['version'] !== undefined) {
      emit('conflict', parsed.message)
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <a-card :bordered="false" class="preference-panel" data-testid="panel-preference">
    <template #title>求职偏好</template>
    <p class="panel-description">
      偏好是可随时调整的规则，不属于履历事实，因此不需要证据，也不会进入资料修订快照。
      <span v-if="isCreate">当前尚未设置；保存即为创建。</span>
    </p>

    <a-alert
      v-if="panelError"
      type="error"
      show-icon
      class="panel-alert"
      :message="panelError.message"
      :description="alertDescription"
      data-testid="error-preference"
    />

    <a-form layout="vertical">
      <a-form-item
        label="目标地点"
        :help="fieldErrors['target_locations'] ?? '输入后回车添加，例如 上海。'"
        :validate-status="fieldErrors['target_locations'] === undefined ? undefined : 'error'"
      >
        <a-select
          :value="targetLocations"
          mode="tags"
          :token-separators="[',']"
          placeholder="上海"
          @update:value="(value: unknown) => (targetLocations = Array.isArray(value) ? (value as string[]) : [])"
        />
      </a-form-item>

      <a-form-item
        label="职位类型"
        :help="fieldErrors['job_types'] ?? '输入后回车添加，例如 全职。'"
        :validate-status="fieldErrors['job_types'] === undefined ? undefined : 'error'"
      >
        <a-select
          :value="jobTypes"
          mode="tags"
          :token-separators="[',']"
          @update:value="(value: unknown) => (jobTypes = Array.isArray(value) ? (value as string[]) : [])"
        />
      </a-form-item>

      <a-row :gutter="16">
        <a-col :span="8">
          <a-form-item
            label="薪资下限（月）"
            :help="fieldErrors['salary_min']"
            :validate-status="fieldErrors['salary_min'] === undefined ? undefined : 'error'"
          >
            <a-input-number :value="salaryMin" class="full-width" @update:value="(value: unknown) => (salaryMin = typeof value === 'number' ? value : null)" />
          </a-form-item>
        </a-col>
        <a-col :span="8">
          <a-form-item
            label="薪资上限（月）"
            :help="fieldErrors['salary_max']"
            :validate-status="fieldErrors['salary_max'] === undefined ? undefined : 'error'"
          >
            <a-input-number :value="salaryMax" class="full-width" @update:value="(value: unknown) => (salaryMax = typeof value === 'number' ? value : null)" />
          </a-form-item>
        </a-col>
        <a-col :span="8">
          <a-form-item
            label="币种"
            :help="fieldErrors['salary_currency'] ?? 'ISO 4217，例如 CNY。'"
            :validate-status="fieldErrors['salary_currency'] === undefined ? undefined : 'error'"
          >
            <a-input :value="salaryCurrency" :maxlength="3" allow-clear @update:value="(value: unknown) => (salaryCurrency = String(value))" />
          </a-form-item>
        </a-col>
      </a-row>

      <a-form-item
        label="远程偏好"
        :help="fieldErrors['remote_preference']"
        :validate-status="fieldErrors['remote_preference'] === undefined ? undefined : 'error'"
      >
        <a-select
          :value="remotePreference"
          :options="remoteOptions"
          allow-clear
          @update:value="(value: unknown) => (remotePreference = typeof value === 'string' ? value : null)"
        />
      </a-form-item>

      <a-form-item
        label="排除条件"
        :help="fieldErrors['exclusions'] ?? '不接受的方向，例如 外包、某行业。'"
        :validate-status="fieldErrors['exclusions'] === undefined ? undefined : 'error'"
      >
        <a-select
          :value="exclusions"
          mode="tags"
          :token-separators="[',']"
          @update:value="(value: unknown) => (exclusions = Array.isArray(value) ? (value as string[]) : [])"
        />
      </a-form-item>

      <a-button type="primary" :loading="saving" data-testid="save-preference" @click="submit">
        {{ isCreate ? '创建偏好' : '保存' }}
      </a-button>
    </a-form>
  </a-card>
</template>

<style scoped>
.preference-panel {
  margin-bottom: 1rem;
}

.panel-description {
  color: #6b7280;
  margin-bottom: 0.75rem;
}

.panel-alert {
  margin-bottom: 1rem;
}

.full-width {
  width: 100%;
}
</style>
