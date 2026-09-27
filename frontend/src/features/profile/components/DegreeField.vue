<script setup lang="ts">
/**
 * 学历/学位选择器。
 *
 * 与城市选择器同一套思路：列表覆盖常见学历，**列表外的值原样保留**。后端 `degree` 是自由字符串，
 * 历史数据与模型抽取都存在"学士""研究生""MBA"这类写法；若选择器把它们吞掉，用户只是编辑学校
 * 就会静默改掉学历。因此值不在列表里时自动切到手动输入回显原文，不猜、不替换。
 *
 * 组件不持有业务状态：值由 `value` 传入，改动经 `updateValue` 冒泡；控件选择后额外冒泡 `blur`，
 * 与其它字段一致，使档案页的"失焦即保存"链路对选择型字段同样成立。
 */

import { computed, ref, watch } from 'vue'

import { DEGREE_OPTIONS, isKnownDegree } from '../degrees'

/** 选择"其他"时控件上的哨兵值：只用于切换控件，永远不会写进档案。 */
const MANUAL = '__manual_degree__'
const options = [...DEGREE_OPTIONS, { value: MANUAL, label: '其他（手动填写）' }]

const props = defineProps<{
  value: string
  disabled?: boolean
  testid?: string
  maxLength?: number
}>()

const emit = defineEmits<{
  updateValue: [value: string]
  blur: []
}>()

const manualSelected = ref(false)

/** 列表外的非空值一律走手动输入：原文保留在输入框里，用户可继续编辑。 */
const manual = computed(() => manualSelected.value || (props.value.trim() !== '' && !isKnownDegree(props.value)))

/** 下拉框当前值；手动模式下不让下拉框显示任何选项，避免"看起来选了硕士其实存的是别的东西"。 */
const selected = computed(() => {
  if (manual.value) return undefined
  return props.value.trim() === '' ? undefined : props.value.trim()
})

watch(
  () => props.value,
  (value) => {
    // 外部（例如切到另一条记录）给了列表内的值就退出手动模式，避免旧的手动状态残留。
    if (isKnownDegree(value)) manualSelected.value = false
  },
)

function select(value: unknown): void {
  if (typeof value !== 'string' || value === '') {
    // 清空：与文本字段一致地提交空字符串，由持有者决定写 null。
    manualSelected.value = false
    emit('updateValue', '')
    emit('blur')
    return
  }
  if (value === MANUAL) {
    manualSelected.value = true
    emit('updateValue', '')
    return
  }
  manualSelected.value = false
  emit('updateValue', value)
  emit('blur')
}
</script>

<template>
  <div class="degree-field">
    <a-select
      :value="selected"
      :options="options"
      :disabled="disabled"
      :placeholder="manual ? '其他学历（在下方填写）' : '请选择学历／学位'"
      :data-testid="testid"
      allow-clear
      show-search
      option-filter-prop="label"
      @change="select"
    />
    <a-input
      v-if="manual"
      :value="value"
      :disabled="disabled"
      :maxlength="maxLength"
      placeholder="填写其他学历或学位（如 研究生、MBA）"
      :data-testid="testid ? `${testid}-manual` : undefined"
      @update:value="(next: string) => emit('updateValue', next)"
      @blur="emit('blur')"
    />
  </div>
</template>

<style scoped>
.degree-field {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.degree-field :deep(.ant-select) {
  width: 100%;
}
</style>
