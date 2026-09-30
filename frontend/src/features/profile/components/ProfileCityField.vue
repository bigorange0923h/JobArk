<script setup lang="ts">
/**
 * 档案城市选择器：使用省市二级数据，最终仍向旧接口提交城市名称字符串。
 * 历史城市和海外地点可能不在中国区划列表里，保留手动输入入口，避免编辑其他字段时丢失旧值。
 */
import { computed, ref, watch } from 'vue'
import { CITY_OPTIONS, MANUAL_CITY, MANUAL_CITY_OPTION, cityPath, displayCity } from '../cityOptions'

const allOptions = [...CITY_OPTIONS, MANUAL_CITY_OPTION]

const props = defineProps<{ value: string; disabled?: boolean; testid?: string; maxLength?: number }>()
const emit = defineEmits<{ updateValue: [value: string]; blur: [] }>()
const manualSelected = ref(false)

const manual = computed(() => manualSelected.value || (props.value.trim() !== '' && cityPath(props.value) === null))
const selectedPath = computed(() => manual.value ? [MANUAL_CITY] : cityPath(props.value))

watch(() => props.value, (value) => {
  if (value.trim() && cityPath(value)) manualSelected.value = false
})

function select(path: (string | number)[] | undefined): void {
  if (!path?.length) {
    manualSelected.value = false
    emit('updateValue', '')
    emit('blur')
    return
  }
  if (path[0] === MANUAL_CITY) {
    manualSelected.value = true
    emit('updateValue', '')
    return
  }
  manualSelected.value = false
  emit('updateValue', String(path[1] ?? ''))
  emit('blur')
}

</script>

<template>
  <div class="city-field">
    <a-cascader
      :value="selectedPath"
      :options="allOptions"
      :disabled="disabled"
      :display-render="displayCity"
      :show-search="true"
      allow-clear
      placeholder="请选择省份和城市"
      :data-testid="testid"
      @change="select"
    />
    <a-input
      v-if="manual"
      :value="value"
      :disabled="disabled"
      :maxlength="maxLength"
      placeholder="填写其他地区或海外城市"
      :data-testid="testid ? `${testid}-manual` : undefined"
      @update:value="(next: string) => emit('updateValue', next)"
      @blur="emit('blur')"
    />
  </div>
</template>

<style scoped>
.city-field { display: grid; gap: 8px; min-width: 0; }
.city-field :deep(.ant-select) { width: 100%; }
</style>
