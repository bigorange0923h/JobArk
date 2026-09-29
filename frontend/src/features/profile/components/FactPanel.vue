<script setup lang="ts" generic="TItem extends EditableResource, TPayload">
/**
 * 由描述符驱动的事实面板：一份表格 + 一个弹窗表单 + 统一的冲突处理。
 *
 * 为什么是通用组件而不是只写当下用到的那一份：这套交互（表格 + 弹窗 + 乐观锁冲突）与字段
 * 无关，机制收敛在这里一次、字段收敛在描述符里，将来再有同类事实只需加一个描述符；写死成
 * 单个实体的实现，第二类事实出现时就只能复制一份，然后各自演化（例如某处忘了清除上一次的
 * 字段错误、某处没有处理版本过期）。技能、经历、项目、教育已改用核心表单
 * （`ProfileFactSections.vue`），不再走这里。
 *
 * 错误处理的分工（对应 `docs/adr/0001` 的错误码表）：
 * - 422 字段级原因：显示在对应字段下方，弹窗保持打开，用户可以就地修正。
 * - 409 版本过期：数据在别处已被修改，就地重试也会失败，因此关闭弹窗并通知页面重新加载。
 * - 其余失败：在面板或弹窗顶部给出后端提示与请求标识。
 *
 * 不做客户端业务规则校验（例如"结束日期不得早于开始日期"）：那是后端的裁决，前端复制一份会
 * 出现两套规则逐渐不一致；这里只做必填检查，其余交给后端返回 422 并定位到字段。
 */

import { computed, nextTick, ref, watch } from 'vue'

import type { EditableResource } from '@/shared/api/types'
import { focusFormTarget, notifyFormIssue } from '@/shared/feedback/formNotice'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import type { FactDescriptor, FieldDescriptor, FieldValues } from '../types'
import FactFieldInput from './FactFieldInput.vue'

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
const advancedOpen = ref<string[]>([])

function factTarget(name: string): HTMLElement | null {
  if (!props.descriptor.fields.some((field) => field.name === name)) return null
  return document.querySelector<HTMLElement>(`[data-testid="panel-${props.descriptor.key}"] [data-testid="fact-field-${name}"]`)
}

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

/** 内容字段：日常编辑就填这些。 */
const primaryFields = computed(() => props.descriptor.fields.filter((field) => field.advanced !== true))

/** 来源与状态这类进阶字段：收进折叠区，始终可选，不影响字段本身的可绑定与提交。 */
const advancedFields = computed(() => props.descriptor.fields.filter((field) => field.advanced === true))

watch(modalOpen, (open) => {
  if (!open) {
    panelError.value = null
    fieldErrors.value = {}
  }
})

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
    const first = missing[0]
    if (first) {
      if (first.advanced) advancedOpen.value = ['source']
      await nextTick()
      focusFormTarget(factTarget(first.name))
      notifyFormIssue({
        kind: 'warning', title: `请补全${props.descriptor.title}`, detail: `「${first.label}」是必填项。`,
        key: `fact-${props.descriptor.key}-required`,
      })
    }
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
  const firstName = Object.keys(parsed.fields)[0]
  if (props.descriptor.fields.some((field) => field.name === firstName && field.advanced)) advancedOpen.value = ['source']
  const target = firstName ? () => factTarget(firstName) : undefined
  notifyFormIssue({
    kind: 'error', title: `${props.descriptor.title}操作失败`, detail: parsed.message,
    key: `fact-${props.descriptor.key}-error`,
  })
  if (target) void nextTick().then(() => focusFormTarget(target()))

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

    <p v-if="panelError && !modalOpen" class="form-error-summary" role="alert" :data-testid="`error-${descriptor.key}`">{{ panelError.message }} {{ alertDescription }}</p>

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
      <p v-if="modalError" class="form-error-summary" role="alert">{{ modalError.message }} {{ alertDescription }}</p>
      <a-form layout="vertical" :model="formValues">
        <a-form-item
          v-for="field in primaryFields"
          :key="field.name"
          :data-testid="`fact-field-${field.name}`"
          :label="field.label"
          :help="fieldErrors[field.name] ?? field.help"
          :validate-status="fieldErrors[field.name] === undefined ? undefined : 'error'"
        >
          <FactFieldInput
            :field="field"
            :value="formValues[field.name]"
            @update="(value: unknown) => setValue(field, value)"
          />
        </a-form-item>

        <!--
          来源与状态是可选信息：日常编辑只填上面的内容即可，来源由导入或本人填写的过程自动记录。
          收进折叠区，需要排查错误或理解匹配依据时展开；`force-render` 让字段始终在 DOM 中，
          折叠与否只影响可见性，不影响表单提交与自动化断言。
        -->
        <a-collapse
          v-if="advancedFields.length > 0"
          v-model:activeKey="advancedOpen"
          ghost
          class="advanced-fields"
          data-testid="fact-advanced-fields"
        >
          <a-collapse-panel key="source" header="来源与状态（可选）" :force-render="true">
            <p class="advanced-hint">
              不填也能保存、参与匹配与生成简历；来源只用于区分「简历原文」与「本人填写」，
              不会把内容变成“已核实”。
            </p>
            <a-form-item
              v-for="field in advancedFields"
              :key="field.name"
              :data-testid="`fact-field-${field.name}`"
              :label="field.label"
              :help="fieldErrors[field.name] ?? field.help"
              :validate-status="fieldErrors[field.name] === undefined ? undefined : 'error'"
            >
              <FactFieldInput
                :field="field"
                :value="formValues[field.name]"
                @update="(value: unknown) => setValue(field, value)"
              />
            </a-form-item>
          </a-collapse-panel>
        </a-collapse>
      </a-form>
    </a-modal>
  </a-card>
</template>

<style scoped>
/* 来源与状态（可选）：不占日常编辑的注意力，但需要时就在表单末尾。 */
.advanced-fields {
  margin-top: 4px;
}

.advanced-hint {
  margin: 0 0 12px;
  color: var(--ja-color-muted);
  font-size: 12px;
  line-height: 1.6;
}

.fact-panel {
  margin-bottom: 1rem;
}

.panel-description {
  color: #6b7280;
  margin-bottom: 0.75rem;
}

.form-error-summary { margin-bottom: 1rem; color: var(--ja-color-danger); font-size: 13px; line-height: 1.6; }

.full-width {
  width: 100%;
}
</style>
