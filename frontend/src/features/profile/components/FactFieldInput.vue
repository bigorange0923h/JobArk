<script setup lang="ts">
/**
 * 单个事实字段的输入控件。
 *
 * 抽成组件是为了让同一份控件实现同时服务"内容字段"与"来源与状态（可选）"两个区域：
 * 复制两份 7 种控件的分支，迟早会出现一份改了另一份没改。
 *
 * 组件只负责把当前值喂给控件、把控件的新值冒泡出去；值的归一化与字段错误仍由 `FactPanel` 处理，
 * 因为那属于表单语义而不是控件语义。
 */

import type { FieldDescriptor } from '../types'
import DegreeField from './DegreeField.vue'

const props = defineProps<{
  field: FieldDescriptor
  /** 当前值；按 `field.kind` 取用其中的字符串、数字或数组。 */
  value: unknown
}>()

const emit = defineEmits<{
  update: [value: unknown]
}>()

function text(): string {
  return typeof props.value === 'string' ? props.value : ''
}

function nullableText(): string | null {
  return typeof props.value === 'string' ? props.value : null
}

function numeric(): number | null {
  return typeof props.value === 'number' ? props.value : null
}

function tags(): string[] {
  return Array.isArray(props.value) ? (props.value as string[]) : []
}
</script>

<template>
  <a-input
    v-if="field.kind === 'text'"
    :value="text()"
    :maxlength="field.maxLength"
    :placeholder="field.placeholder"
    allow-clear
    @update:value="(value: unknown) => emit('update', value)"
  />
  <a-textarea
    v-else-if="field.kind === 'textarea'"
    :value="text()"
    :maxlength="field.maxLength"
    :rows="3"
    allow-clear
    @update:value="(value: unknown) => emit('update', value)"
  />
  <a-input-number
    v-else-if="field.kind === 'number'"
    :value="numeric()"
    class="full-width"
    @update:value="(value: unknown) => emit('update', value)"
  />
  <a-date-picker
    v-else-if="field.kind === 'date'"
    :value="nullableText()"
    value-format="YYYY-MM-DD"
    class="full-width"
    allow-clear
    @update:value="(value: unknown) => emit('update', value)"
  />
  <DegreeField
    v-else-if="field.kind === 'degree'"
    :value="text()"
    :maxlength="field.maxLength"
    @update-value="(value: string) => emit('update', value)"
  />
  <a-select
    v-else-if="field.kind === 'select' || field.kind === 'evidence'"
    :value="nullableText()"
    :options="field.options ?? []"
    allow-clear
    show-search
    option-filter-prop="label"
    @update:value="(value: unknown) => emit('update', value)"
  />
  <a-select
    v-else-if="field.kind === 'tags'"
    :value="tags()"
    mode="tags"
    :token-separators="[',']"
    @update:value="(value: unknown) => emit('update', value)"
  />
</template>

<style scoped>
.full-width {
  width: 100%;
}
</style>
