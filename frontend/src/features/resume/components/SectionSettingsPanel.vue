<script setup lang="ts">
/**
 * 模块设置面板：调整六个固定模块的展示顺序与显隐。
 *
 * 桌面端支持拖动排序；聚焦模块行后可用方向键排序，不占用可见按钮空间。
 *
 * 面板不因为某个模块暂时为空就替用户关掉它：空模块本来就不会渲染（见 `renderedSections`），
 * 但写进 `hidden_sections` 会让"暂时没填"变成用户的选择——用户后来填了内容却看不到，
 * 而界面上找不到是谁关掉的。
 */

import { computed, ref } from 'vue'

import type { ResumeDocument, ResumeSection } from '@/shared/api/resume'

import { SECTION_LABEL, SECTION_ORDER_DEFAULT, isSectionEmpty, moveSection, setSectionHidden } from '../document'

/** 当前文档；组件通过 `v-model` 提交改动后的整份文档。 */
const document = defineModel<ResumeDocument>({ required: true })
const dragging = ref<ResumeSection | null>(null)
const hovered = ref<ResumeSection | null>(null)
const isDefaultLayout = computed(() =>
  document.value.hidden_sections.length === 0 &&
  document.value.section_order.every((section, index) => section === SECTION_ORDER_DEFAULT[index]),
)

/** 按当前顺序展开的面板行。 */
const rows = computed(() =>
  document.value.section_order.map((section) => ({
    section,
    label: SECTION_LABEL[section],
    empty: isSectionEmpty(document.value, section),
    visible: !document.value.hidden_sections.includes(section),
  })),
)

/**
 * 提交顺序调整。
 *
 * 参数:
 *     section: 被移动的模块。
 *     direction: 移动方向。
 */
function submitOrder(section: ResumeSection, direction: 'up' | 'down'): void {
  document.value = {
    ...document.value,
    section_order: moveSection(document.value.section_order, section, direction),
  }
}

/** 只处理模块行本身的方向键，避免拦截显隐开关等子控件的键盘操作。 */
function onRowKeydown(event: KeyboardEvent, section: ResumeSection, direction: 'up' | 'down'): void {
  if (event.target !== event.currentTarget) return
  event.preventDefault()
  submitOrder(section, direction)
}

/** 拖出当前行时取消高亮；进入行内子元素不算离开，避免闪烁。 */
function leaveTarget(event: DragEvent, section: ResumeSection): void {
  const row = event.currentTarget
  if (row instanceof HTMLElement && event.relatedTarget instanceof Node && row.contains(event.relatedTarget)) return
  if (hovered.value === section) hovered.value = null
}

/** 拖动只改变固定模块的排列，不增删模块或修改显隐。 */
function dropOn(target: ResumeSection): void {
  const source = dragging.value
  dragging.value = null
  hovered.value = null
  if (!source || source === target) return
  const order = [...document.value.section_order]
  const from = order.indexOf(source)
  const to = order.indexOf(target)
  if (from < 0 || to < 0) return
  order.splice(from, 1)
  order.splice(to, 0, source)
  document.value = { ...document.value, section_order: order }
}

/**
 * 提交显隐改动。
 *
 * 参数:
 *     section: 模块。
 *     checked: 开关的新状态；只有严格等于 true 才算"显示"。
 *
 * 注意:
 *     这里按 `unknown` 接收而不是写成具体类型：`components.d.ts` 是构建时生成的，而它的更新
 *     滞后于首次构建（实测：引入该组件的首次构建没有写入声明，后续构建才写入），因此"事件参数
 *     可被推断"这件事取决于构建时序。按 `unknown` 接收并用 `!== true` 判定，使这里不依赖那个
 *     时序；运行时的实际取值由测试固定（AntDV 的开关提交布尔值）。
 */
function submitVisibility(section: ResumeSection, checked: unknown): void {
  document.value = {
    ...document.value,
    hidden_sections: setSectionHidden(document.value.hidden_sections, section, checked !== true),
  }
}

/** 仅重置排版元数据；正文、条目与来源关联必须原样保留。 */
function restoreDefaultLayout(): void {
  if (isDefaultLayout.value) return
  dragging.value = null
  hovered.value = null
  document.value = {
    ...document.value,
    section_order: [...SECTION_ORDER_DEFAULT],
    hidden_sections: [],
  }
}
</script>

<template>
  <div class="section-settings" aria-label="模板管理">
    <p class="panel-hint">拖动排序；键盘聚焦模块后可用 ↑ ↓ 调整</p>
    <ul class="section-rows">
      <li
        v-for="row in rows"
        :key="row.section"
        class="section-row"
        :class="{ 'section-row--drop-target': hovered === row.section }"
        draggable="true"
        tabindex="0"
        :aria-label="`${row.label}，可拖动或按上下方向键调整顺序`"
        @dragstart="dragging = row.section; hovered = null"
        @dragover.prevent="hovered = dragging && dragging !== row.section ? row.section : null"
        @dragleave="leaveTarget($event, row.section)"
        @drop.prevent="dropOn(row.section)"
        @dragend="dragging = null; hovered = null"
        @keydown.up="onRowKeydown($event, row.section, 'up')"
        @keydown.down="onRowKeydown($event, row.section, 'down')"
        :data-testid="`section-row-${row.section}`"
      >
        <span class="drag-handle" aria-hidden="true">⠿</span>
        <span class="section-label">{{ row.label }}</span>
        <span v-if="row.empty" class="section-empty-hint" title="暂无内容，不会出现在预览中">暂无内容</span>

        <span class="section-actions">
          <a-switch
            :checked="row.visible"
            :data-testid="`section-visibility-${row.section}`"
            :aria-label="`${row.label}显示在预览中`"
            @change="submitVisibility(row.section, $event)"
          />
        </span>
      </li>
    </ul>
    <div class="panel-footer">
      <a-button size="small" :disabled="isDefaultLayout" data-testid="restore-default-layout" @click="restoreDefaultLayout">恢复默认排版</a-button>
    </div>
  </div>
</template>

<style scoped>
.section-settings { width: 310px; max-width: calc(100vw - 48px); }
.section-rows {
  list-style: none;
  margin: 0;
  padding: 0;
}

.section-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 40px;
  padding: 0.3rem 0;
  border-bottom: 1px solid #f3f4f6;
  cursor: grab;
}
.section-row:active { cursor: grabbing; }
.section-row:focus-visible { outline: 2px solid var(--ja-color-primary); outline-offset: -2px; }
.section-row--drop-target { background: #1677ff; color: #fff; border-radius: 4px; }
.section-row--drop-target .drag-handle,
.section-row--drop-target .section-empty-hint { color: #fff; }
.drag-handle { color: #9ca3af; }

.section-row:last-child {
  border-bottom: none;
}

.section-label {
  min-width: 0;
  font-weight: 500;
}

.section-empty-hint,
.panel-hint {
  color: #9ca3af;
  font-size: 0.8rem;
}

.section-actions {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  margin-left: auto;
}
.panel-hint { margin: 0 0 6px; }
.panel-footer { display: flex; justify-content: flex-end; padding-top: 12px; }
</style>
