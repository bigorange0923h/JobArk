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

import { savePreference, type Preference, type PreferenceInput, type RemotePreference, type HardLimits, type PriorityRule } from '@/shared/api/profile'
import { isGlobalFailure, notifyFailure } from '@/shared/feedback/failureNotice'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import { REMOTE_PREFERENCE_LABELS } from '../descriptors'
import type { FieldOption } from '../types'
import ProfileTargetLocationsField from './ProfileTargetLocationsField.vue'

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
const targetRoles = ref<string[]>([])
const roleKeywords = ref<string[]>([])
const acceptableSalaryMin = ref<number | null>(null)
const hardLimits = ref<HardLimits>({ location: false, employment_type: false, remote: false, salary: false, salary_basis: null })
const priorityRules = ref<PriorityRule[]>([])
const priorityValue = ref('')
const priorityKind = ref<PriorityRule['kind']>('COMPANY_NAME')
/** 只创建完整名称、行业代码或关键词，不开放自由正则。 */
function addPriority(): void {
  if (!priorityValue.value.trim()) return
  priorityRules.value.push({ id: crypto.randomUUID(), kind: priorityKind.value, value: priorityValue.value.trim(), enabled: true })
  priorityValue.value = ''
}
const fieldErrors = ref<Record<string, string>>({})
const panelError = ref<ParsedServerError | null>(null)
const saving = ref(false)

const remoteOptions: FieldOption[] = Object.entries(REMOTE_PREFERENCE_LABELS).map(([value, label]) => ({ value, label }))
const jobTypeOptions: FieldOption[] = ['全职', '兼职', '实习', '合同制'].map((value) => ({ value, label: value }))
const currencyOptions: FieldOption[] = ['CNY', 'USD', 'HKD', 'EUR', 'GBP', 'JPY'].map((value) => ({ value, label: value }))

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
    targetRoles.value = [...(preference?.target_roles ?? [])]
    roleKeywords.value = [...(preference?.role_keywords ?? [])]
    acceptableSalaryMin.value = preference?.acceptable_salary_min ?? null
    hardLimits.value = { location: false, employment_type: false, remote: false, salary: false, salary_basis: null, ...preference?.hard_limits }
    priorityRules.value = (preference?.priority_rules ?? []).map(rule => ({ ...rule }))
    fieldErrors.value = {}
    panelError.value = null
  },
  { immediate: true },
)

async function submit(): Promise<void> {
  if (saving.value) return
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
      target_roles: targetRoles.value,
      role_keywords: roleKeywords.value,
      acceptable_salary_min: acceptableSalaryMin.value,
      hard_limits: hardLimits.value,
      priority_rules: priorityRules.value,
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
    // 字段错误与版本冲突留在表单上下文里；无法定位字段的失败走全局通知。
    const global = isGlobalFailure(parsed)
    panelError.value = global ? null : parsed
    if (global) {
      notifyFailure(parsed, '保存求职偏好')
    }
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
      <a-form-item label="目标岗位方向" :help="fieldErrors['target_roles']" :validate-status="fieldErrors['target_roles'] === undefined ? undefined : 'error'" extra="本人明确声明，例如 AI应用开发、Java后端；结合职位标题和职责核对，留空不推测意愿。"><a-select v-model:value="targetRoles" mode="tags" data-testid="target-roles" /></a-form-item>
      <a-form-item label="补充方向关键词" :help="fieldErrors['role_keywords']" :validate-status="fieldErrors['role_keywords'] === undefined ? undefined : 'error'" extra="例如 RAG、Agent；只作为方向线索，不代替目标岗位。"><a-select v-model:value="roleKeywords" mode="tags" data-testid="role-keywords" /></a-form-item>
      <a-form-item label="最低可接受月薪（选填）" :validate-status="fieldErrors['acceptable_salary_min'] === undefined ? undefined : 'error'" :help="fieldErrors['acceptable_salary_min'] ?? '独立于期望区间；留空且启用硬限制时沿用原期望下限。'"><a-input-number v-model:value="acceptableSalaryMin" :min="0" data-testid="acceptable-salary-min" /></a-form-item>
      <a-form-item label="硬限制（默认关闭）" extra="开启后未知信息须先确认；旧偏好保持软偏好。">
        <a-space wrap><a-checkbox v-model:checked="hardLimits.location">地点</a-checkbox><a-checkbox v-model:checked="hardLimits.employment_type">雇佣类型</a-checkbox><a-checkbox v-model:checked="hardLimits.remote">工作方式</a-checkbox><a-checkbox v-model:checked="hardLimits.salary">最低月薪</a-checkbox></a-space>
      </a-form-item>
      <a-form-item label="薪资比较口径" :help="fieldErrors['hard_limits.salary_basis']" :validate-status="fieldErrors['hard_limits.salary_basis'] === undefined ? undefined : 'error'" extra="税口径未知不做确定比较。"><a-select v-model:value="hardLimits.salary_basis" allow-clear :options="[{ value: 'GROSS', label: '税前' }, { value: 'NET', label: '税后' }]" /></a-form-item>
      <a-form-item label="优先名单" extra="任一命中表示优先关注；不增加适配分，也不抵消黑名单。">
        <a-space wrap><a-select v-model:value="priorityKind" :options="[{ value: 'COMPANY_NAME', label: '完整公司名' }, { value: 'COMPANY_INDUSTRY', label: '确认行业代码' }, { value: 'JD_KEYWORD', label: '岗位关键词' }]" /><a-input v-model:value="priorityValue" :maxlength="200" /><a-button @click="addPriority">添加优先规则</a-button></a-space>
        <div v-for="(rule, index) in priorityRules" :key="rule.id"><a-checkbox v-model:checked="rule.enabled">{{ rule.value }}</a-checkbox><a-button type="link" @click="priorityRules.splice(index, 1)">移除</a-button></div>
      </a-form-item>
      <a-form-item
        label="目标地点"
        :help="fieldErrors['target_locations'] ?? '按省份选择多个城市；旧称、其他地区或海外城市可手动添加。'"
        :validate-status="fieldErrors['target_locations'] === undefined ? undefined : 'error'"
      >
        <ProfileTargetLocationsField
          :value="targetLocations"
          :disabled="saving"
          @update-value="(value: string[]) => (targetLocations = value)"
        />
      </a-form-item>

      <a-form-item
        label="职位类型"
        :help="fieldErrors['job_types'] ?? '优先选择常见类型；列表外的职位类型仍可输入后回车添加。'"
        :validate-status="fieldErrors['job_types'] === undefined ? undefined : 'error'"
      >
        <a-select
          :value="jobTypes"
          mode="tags"
          :options="jobTypeOptions"
          show-search
          option-filter-prop="label"
          :token-separators="[',']"
          @update:value="(value: unknown) => (jobTypes = Array.isArray(value) ? (value as string[]) : [])"
        />
      </a-form-item>

      <a-row :gutter="16">
        <a-col :xs="24" :md="8">
          <a-form-item
            label="期望月薪下限"
            :help="fieldErrors['salary_min']"
            :validate-status="fieldErrors['salary_min'] === undefined ? undefined : 'error'"
          >
            <a-input-number :value="salaryMin" class="full-width" @update:value="(value: unknown) => (salaryMin = typeof value === 'number' ? value : null)" />
          </a-form-item>
        </a-col>
        <a-col :xs="24" :md="8">
          <a-form-item
            label="期望月薪上限（更高不扣分）"
            :help="fieldErrors['salary_max']"
            :validate-status="fieldErrors['salary_max'] === undefined ? undefined : 'error'"
          >
            <a-input-number :value="salaryMax" class="full-width" @update:value="(value: unknown) => (salaryMax = typeof value === 'number' ? value : null)" />
          </a-form-item>
        </a-col>
        <a-col :xs="24" :md="8">
          <a-form-item
            label="币种"
            :help="fieldErrors['salary_currency'] ?? '优先选择常用币种；其他 ISO 4217 代码可手动输入。'"
            :validate-status="fieldErrors['salary_currency'] === undefined ? undefined : 'error'"
          >
            <a-auto-complete :value="salaryCurrency" :options="currencyOptions" :maxlength="3" allow-clear @update:value="(value: string) => (salaryCurrency = value)" />
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

      <a-form-item label="历史排除标签" extra="原样保留供查看，不参与自动判定；请在下方分类添加正式规则。">
        <a-tag v-for="(label, index) in exclusions" :key="index">{{ label }}</a-tag>
        <span v-if="exclusions.length === 0">暂无历史标签</span>
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
