<script setup lang="ts" generic="TItem extends EditableResource, TPayload">
/**
 * 由描述符驱动的事实面板：一份表格 + 一个弹窗表单 + 统一的冲突处理。
 *
 * 为什么是通用组件而不是六份实现：证据、技能、经历、项目、教育、语言的交互完全同构，
 * 差异只有字段。六份复制品会各自演化（例如某处忘了清除上一次的字段错误、某处没有处理
 * 版本过期），而这类差异只在特定操作顺序下才暴露。机制收敛在这里一次，字段收敛在描述符里。
 *
 * 错误处理的分工（对应 `docs/adr/0001` 的错误码表）：
 * - 422 字段级原因：显示在对应字段下方，弹窗保持打开，用户可以就地修正。
 * - 409 版本过期：数据在别处已被修改，就地重试也会失败，因此关闭弹窗并通知页面重新加载。
 * - 其余失败：在面板或弹窗顶部给出后端提示与请求标识。
 *
 * 不做客户端业务规则校验（例如"结束日期不得早于开始日期"）：那是后端的裁决，前端复制一份会
 * 出现两套规则逐渐不一致；这里只做必填检查，其余交给后端返回 422 并定位到字段。
 */

import { computed, ref, watch } from 'vue'

import type { EditableResource } from '@/shared/api/profile'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import type { FactDescriptor, FieldDescriptor, FieldValues } from '../types'

const props = defineProps<{
  /** 该事实的字段、列与写操作。 */
  descriptor: FactDescriptor<TItem, TPayload>
  /** 当前记录；来自档案聚合，不由本组件请求。 */
  items: readonly TItem[]
}>()

const emit = defineEmits<{
  /** 写入成功，页面应重新加载档案聚合以取得一致的视图。 */
  changed: []
  /** 版本过期等需要刷新才能继续的冲突。 */
  conflict: [message: string]
}>()

const modalOpen = ref(false)
const editing = ref<TItem | null>(null)
const formValues = ref<FieldValues>({})
const fieldErrors = ref<Record<string, string>>({})
const panelError = ref<ParsedServerError | null>(null)
const submitting = ref(false)

const removeLabel = computed(() => props.descriptor.removeLabel ?? '删除')

const modalTitle = computed(() =>
  editing.value === null ? `新增${props.descriptor.title}` : `编辑${props.descriptor.title}`,
)

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

/** 表格列：描述符列 + 固定的操作列。 */
const tableColumns = computed(() => [
  ...props.descriptor.columns.map((column) => ({ title: column.label, key: column.name, dataIndex: column.name })),
  { title: '操作', key: 'actions' },
])

/** 弹窗内的错误提示只在弹窗打开时显示，避免与面板上的删除错误混在一起。 */
const modalError = computed(() => (modalOpen.value ? panelError.value : null))

watch(modalOpen, (open) => {
  if (!open) {
    panelError.value = null
    fieldErrors.value = {}
  }
})

/**
 * 把界面值收窄成模板可绑定的类型。
 *
 * 表单值以 `unknown` 存储（字段是动态的），模板需要一个明确类型才能绑定到组件属性；
 * 在这里逐类收窄，而不是把整个表单降级成 `any` 从而失去类型检查。
 */
function textOf(name: string): string {
  const value = formValues.value[name]
  return typeof value === 'string' ? value : ''
}

function numberOf(name: string): number | null {
  const value = formValues.value[name]
  return typeof value === 'number' ? value : null
}

function valueOf(name: string): string | null {
  const value = formValues.value[name]
  return typeof value === 'string' ? value : null
}

function tagsOf(name: string): string[] {
  const value = formValues.value[name]
  return Array.isArray(value) ? (value as string[]) : []
}

function selectOptions(field: FieldDescriptor): { value: string; label: string }[] {
  return field.options ?? []
}

/** 写入一个字段值，并清除该字段上一次的服务端错误。 */
function setValue(field: FieldDescriptor, value: unknown): void {
  formValues.value[field.name] = normalize(field, value)
  if (fieldErrors.value[field.name] !== undefined) {
    const remaining = { ...fieldErrors.value }
    delete remaining[field.name]
    fieldErrors.value = remaining
  }
}

/**
 * 归一化界面值。
 *
 * 两处必要的原因：控件给的 `undefined`（清空选择）与 `''`（清空文本框）在后端分别对应
 * "不修改"与"设为空字符串"，而本界面提交的始终是完整字段集，因此统一转成 `null`，
 * 语义是"该字段为空"。
 */
function normalize(field: FieldDescriptor, value: unknown): unknown {
  if (field.kind === 'number') {
    if (value === null || value === undefined || value === '') {
      return null
    }
    const parsed = Number(value)
    return Number.isNaN(parsed) ? null : parsed
  }
  if (field.kind === 'tags') {
    return Array.isArray(value) ? value : []
  }
  if (value === undefined || value === '') {
    return null
  }
  return value
}

function initialValues(item: TItem | null): FieldValues {
  const values: FieldValues = {}
  for (const field of props.descriptor.fields) {
    const raw = item === null ? null : (item as unknown as FieldValues)[field.name]
    values[field.name] = normalize(field, raw)
  }
  return values
}

function openCreate(): void {
  editing.value = null
  formValues.value = initialValues(null)
  fieldErrors.value = {}
  panelError.value = null
  modalOpen.value = true
}

function openEdit(item: TItem): void {
  editing.value = item
  formValues.value = initialValues(item)
  fieldErrors.value = {}
  panelError.value = null
  modalOpen.value = true
}

/**
 * 构造请求体。
 *
 * 这里是一次有意的类型断言：描述符的字段名与后端请求体字段名一一对应（描述符即二者之间的字段
 * 契约），因此表单值天然就是请求体。断言让通用面板不必为每个实体重写一遍字段映射，代价是字段名
 * 写错时不会有编译错误——只能由后端 422 或接口测试暴露。
 */
function buildPayload(): TPayload {
  return { ...formValues.value } as TPayload
}

async function submit(): Promise<void> {
  const missing = props.descriptor.fields.filter((field) => field.required === true && isEmpty(formValues.value[field.name]))
  if (missing.length > 0) {
    const errors: Record<string, string> = {}
    for (const field of missing) {
      errors[field.name] = '该项为必填。'
    }
    fieldErrors.value = errors
    return
  }

  const current = editing.value
  submitting.value = true
  panelError.value = null
  try {
    const payload = buildPayload()
    if (current === null) {
      await props.descriptor.operations.create(payload)
    } else {
      await props.descriptor.operations.update(current.id, { ...payload, version: current.version })
    }
    closeModal()
    emit('changed')
  } catch (error: unknown) {
    handleWriteError(error)
  } finally {
    submitting.value = false
  }
}

async function remove(item: TItem): Promise<void> {
  panelError.value = null
  try {
    await props.descriptor.operations.remove(item.id)
    emit('changed')
  } catch (error: unknown) {
    handleWriteError(error)
  }
}

/**
 * 统一的写入失败处理。
 *
 * 判定"版本过期"的依据是错误码为 `CONFLICT` 且细节里带有 `version` 字段：仅仅看到 409 不够，
 * 因为"删除被修订引用的记录"同样是 409，但那种情况重新加载并不会让操作变得可行，
 * 只能把原因告诉用户。
 */
function handleWriteError(error: unknown): void {
  const parsed = parseServerError(error)
  fieldErrors.value = parsed.fields
  panelError.value = parsed

  if (parsed.code === 'CONFLICT' && parsed.fields['version'] !== undefined) {
    closeModal()
    emit('conflict', parsed.message)
  }
}

/** 关闭弹窗；集中一处，避免散落的赋值让"关闭"这一动作有多个变体。 */
function closeModal(): void {
  modalOpen.value = false
}

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === ''
}

/** AntDV 的表格插槽把行数据声明为任意类型，断言集中在此，避免散落到模板表达式里。 */
function asItem(record: unknown): TItem {
  return record as TItem
}

function rowKeyOf(record: unknown): string {
  return asItem(record).id
}

function rowLabelOf(record: unknown): string {
  return props.descriptor.rowLabel(asItem(record))
}

function cellText(columnKey: string, item: TItem): string {
  const column = props.descriptor.columns.find((candidate) => candidate.name === columnKey)
  if (column === undefined) {
    return '—'
  }
  if (column.format !== undefined) {
    return column.format(item)
  }
  const raw = (item as unknown as FieldValues)[columnKey]
  if (raw === null || raw === undefined || raw === '') {
    return '—'
  }
  return String(raw)
}
</script>

<template>
  <a-card :bordered="false" class="fact-panel" :data-testid="`panel-${descriptor.key}`">
    <template #title>{{ descriptor.title }}</template>
    <template #extra>
      <a-button type="primary" size="small" data-testid="create" @click="openCreate">新增</a-button>
    </template>

    <p class="panel-description">{{ descriptor.description }}</p>

    <a-alert
      v-if="panelError && !modalOpen"
      type="error"
      show-icon
      class="panel-alert"
      :message="panelError.message"
      :description="alertDescription"
      :data-testid="`error-${descriptor.key}`"
    />

    <a-table
      :data-source="items"
      :columns="tableColumns"
      :pagination="false"
      :row-key="rowKeyOf"
      size="small"
      :locale="{ emptyText: '暂无记录' }"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'actions'">
          <a-space>
            <a-button type="link" size="small" @click="openEdit(asItem(record))">编辑</a-button>
            <a-popconfirm
              :title="`确认${removeLabel}「${rowLabelOf(record)}」？`"
              ok-text="确认"
              cancel-text="取消"
              @confirm="remove(asItem(record))"
            >
              <a-button type="link" size="small" danger>{{ removeLabel }}</a-button>
            </a-popconfirm>
          </a-space>
        </template>
        <template v-else>{{ cellText(String(column.key), asItem(record)) }}</template>
      </template>
    </a-table>

    <!--
      弹窗的可见性由 `v-if` 控制，而不是用 `v-model:open` 切换：
      关闭时直接卸载组件，不经过"离开动画 + 传送门移除"这条路径——那条路径在 jsdom 下会抛
      DOM 错误，而错误发生在关闭动作之后，会把紧随其后的 `emit` 一起吞掉，表现为难以定位的
      行为差异。`v-if` 同时让"弹窗是否打开"成为可直接断言的渲染事实。
      代价是每次打开都是全新实例，因此表单状态必须在打开时显式初始化（见 openCreate/openEdit）。
      同时不启用到 body 的传送门（`:get-container="false"`）：弹窗因此属于组件子树，
      断言"弹窗是否打开"时不必去 `document.body` 里找，也不会在页面里留下游离节点。
    -->
    <a-modal
      v-if="modalOpen"
      :open="true"
      :title="modalTitle"
      :confirm-loading="submitting"
      :get-container="false"
      ok-text="保存"
      cancel-text="取消"
      @ok="submit"
      @cancel="modalOpen = false"
    >
      <a-alert
        v-if="modalError"
        type="error"
        show-icon
        class="modal-alert"
        :message="modalError.message"
        :description="alertDescription"
      />
      <a-form layout="vertical" :model="formValues">
        <a-form-item
          v-for="field in descriptor.fields"
          :key="field.name"
          :label="field.label"
          :help="fieldErrors[field.name] ?? field.help"
          :validate-status="fieldErrors[field.name] === undefined ? undefined : 'error'"
        >
          <a-input
            v-if="field.kind === 'text'"
            :value="textOf(field.name)"
            :maxlength="field.maxLength"
            :placeholder="field.placeholder"
            allow-clear
            @update:value="(value: unknown) => setValue(field, value)"
          />
          <a-textarea
            v-else-if="field.kind === 'textarea'"
            :value="textOf(field.name)"
            :maxlength="field.maxLength"
            :rows="3"
            allow-clear
            @update:value="(value: unknown) => setValue(field, value)"
          />
          <a-input-number
            v-else-if="field.kind === 'number'"
            :value="numberOf(field.name)"
            class="full-width"
            @update:value="(value: unknown) => setValue(field, value)"
          />
          <a-date-picker
            v-else-if="field.kind === 'date'"
            :value="valueOf(field.name)"
            value-format="YYYY-MM-DD"
            class="full-width"
            allow-clear
            @update:value="(value: unknown) => setValue(field, value)"
          />
          <a-select
            v-else-if="field.kind === 'select' || field.kind === 'evidence'"
            :value="valueOf(field.name)"
            :options="selectOptions(field)"
            allow-clear
            show-search
            option-filter-prop="label"
            @update:value="(value: unknown) => setValue(field, value)"
          />
          <a-select
            v-else-if="field.kind === 'tags'"
            :value="tagsOf(field.name)"
            mode="tags"
            :token-separators="[',']"
            @update:value="(value: unknown) => setValue(field, value)"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </a-card>
</template>

<style scoped>
.fact-panel {
  margin-bottom: 1rem;
}

.panel-description {
  color: #6b7280;
  margin-bottom: 0.75rem;
}

.panel-alert,
.modal-alert {
  margin-bottom: 1rem;
}

.full-width {
  width: 100%;
}
</style>
