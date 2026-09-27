<script setup lang="ts">
/**
 * 档案城市选择器：使用省市二级数据，最终仍向旧接口提交城市名称字符串。
 * 历史城市和海外地点可能不在中国区划列表里，保留手动输入入口，避免编辑其他字段时丢失旧值。
 */
import { computed, ref, watch } from 'vue'
import { pc } from 'cn-division'

const MANUAL = '__manual_city__'
const options = Object.entries(pc).map(([province, cities]) => ({
  label: province,
  value: province,
  children: Object.keys(cities).filter((city) => city !== '县').map((city) => ({ label: city, value: city })),
}))
const manualOption = { label: '其他地区／海外（手动填写）', value: MANUAL }
const allOptions = [...options, manualOption]

const props = defineProps<{ value: string; disabled?: boolean; testid?: string; maxLength?: number }>()
const emit = defineEmits<{ updateValue: [value: string]; blur: [] }>()
const manualSelected = ref(false)

/** 兼容旧库的“上海”“哈尔滨”和新选项的“上海市”“哈尔滨市”，不改写旧值。 */
function locationPath(value: string): string[] | null {
  const clean = value.trim()
  if (!clean) return null
  for (const province of options) {
    const city = province.children.find((entry) =>
      entry.value === clean || entry.value.replace(/市$/, '') === clean ||
      `${province.value}${entry.value}` === clean,
    )
    if (city) return [province.value, city.value]
  }
  return null
}

const manual = computed(() => manualSelected.value || (props.value.trim() !== '' && locationPath(props.value) === null))
const selectedPath = computed(() => manual.value ? [MANUAL] : locationPath(props.value))

watch(() => props.value, (value) => {
  if (value.trim() && locationPath(value)) manualSelected.value = false
})

function select(path: (string | number)[] | undefined): void {
  if (!path?.length) {
    manualSelected.value = false
    emit('updateValue', '')
    emit('blur')
    return
  }
  if (path[0] === MANUAL) {
    manualSelected.value = true
    emit('updateValue', '')
    return
  }
  manualSelected.value = false
  emit('updateValue', String(path[1] ?? ''))
  emit('blur')
}

function displayPath({ labels }: { labels: string[] }): string {
  return labels.at(-1) ?? ''
}
</script>

<template>
  <div class="city-field">
    <a-cascader
      :value="selectedPath"
      :options="allOptions"
      :disabled="disabled"
      :display-render="displayPath"
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
