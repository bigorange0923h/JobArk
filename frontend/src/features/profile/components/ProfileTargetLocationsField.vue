<script setup lang="ts">
/** 求职目标地点：省市多选树；旧值和海外地点保留原文并提供手动兜底。 */
import { computed, ref } from 'vue'
import { CITY_OPTIONS, MANUAL_CITY, MANUAL_CITY_OPTION, cityPath, displayCity } from '../cityOptions'

const props = defineProps<{ value: string[]; disabled?: boolean }>()
const emit = defineEmits<{ updateValue: [value: string[]] }>()
const manualText = ref('')
const manualSelected = ref(false)
const allOptions = [...CITY_OPTIONS, MANUAL_CITY_OPTION]

const selectedPaths = computed(() => {
  const paths = new Map<string, string[]>()
  for (const value of props.value) {
    const path = cityPath(value)
    if (path) paths.set(path.join('\u0000'), path)
  }
  return [...paths.values()]
})
const unmapped = computed(() => props.value.filter((value) => cityPath(value) === null))

/** 选项新值带省份，避免不同省份同名城市无法区分；既有值沿用原字符串。 */
function select(paths: unknown): void {
  if (!Array.isArray(paths)) return
  if (paths.some((path) => Array.isArray(path) && path[0] === MANUAL_CITY)) manualSelected.value = true
  const selected = paths
    .filter((path): path is (string | number)[] => Array.isArray(path) && path.length === 2)
    .map((path) => [String(path[0]), String(path[1])])
  const selectedKeys = new Set(selected.map((path) => path.join('\u0000')))
  // 原有值与相对顺序都保留；只有用户从树里移除的已映射城市才删除。
  const retained = props.value.filter((value) => {
    const path = cityPath(value)
    return path === null || selectedKeys.has(path.join('\u0000'))
  })
  const retainedKeys = new Set(retained.map(cityPath).filter((path): path is string[] => path !== null).map((path) => path.join('\u0000')))
  const added = selected.filter((path) => !retainedKeys.has(path.join('\u0000'))).map(([province, city]) => `${province}${city}`)
  emit('updateValue', [...new Set([...retained, ...added])])
}

/** 只有在用户明确提交手动项时才写入，避免空白或输入中的文本混入已保存偏好。 */
function addManual(): void {
  const value = manualText.value.trim()
  if (!value) return
  if (!props.value.includes(value)) emit('updateValue', [...props.value, value])
  manualText.value = ''
}

function removeManual(value: string): void {
  emit('updateValue', props.value.filter((item) => item !== value))
}

</script>

<template>
  <div class="target-locations">
    <!-- 必须返回城市叶子路径：默认合并为省级值会被两级路径校验丢弃，直辖市选一个即触发。 -->
    <a-cascader
      :value="selectedPaths"
      :options="allOptions"
      :disabled="disabled"
      :display-render="displayCity"
      :show-search="true"
      show-checked-strategy="SHOW_CHILD"
      multiple
      allow-clear
      placeholder="请选择省份和城市"
      data-testid="target-locations-tree"
      @update:value="select"
    />
    <div v-if="unmapped.length" class="legacy-locations" aria-label="其他目标地点">
      <a-tag v-for="value in unmapped" :key="value" :closable="!disabled" @close="removeManual(value)">{{ value }}</a-tag>
    </div>
    <div v-if="manualSelected" class="manual-location">
      <a-input
        v-model:value="manualText"
        :disabled="disabled"
        :maxlength="100"
        placeholder="填写其他地区或海外城市"
        data-testid="target-location-manual"
        @press-enter="addManual"
      />
      <a-button :disabled="disabled || !manualText.trim()" data-testid="target-location-add-manual" @click="addManual">添加其他地点</a-button>
    </div>
  </div>
</template>

<style scoped>
.target-locations { display: grid; gap: 8px; min-width: 0; }
.target-locations :deep(.ant-select) { width: 100%; }
.legacy-locations { display: flex; flex-wrap: wrap; gap: 4px; }
.manual-location { display: flex; flex-wrap: wrap; gap: 8px; }
.manual-location :deep(.ant-input) { flex: 1 1 220px; }
</style>
