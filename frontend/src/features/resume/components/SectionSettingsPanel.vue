<script setup lang="ts">
/**
 * 模块设置面板：调整六个固定模块的展示顺序与显隐。
 *
 * 只提供"上移/下移"而不做拖拽：六个模块的调整是低频操作，相邻交换足够表达意图，
 * 而拖拽需要同时处理指针、键盘与触屏三套交互，代价与收益不成比例。
 *
 * 面板不因为某个模块暂时为空就替用户关掉它：空模块本来就不会渲染（见 `renderedSections`），
 * 但写进 `hidden_sections` 会让"暂时没填"变成用户的选择——用户后来填了内容却看不到，
 * 而界面上找不到是谁关掉的。
 */

import { computed } from 'vue'

import type { ResumeDocument, ResumeSection } from '@/shared/api/resume'

import { SECTION_LABEL, isSectionEmpty, moveSection, setSectionHidden } from '../document'

/** 当前文档；组件通过 `v-model` 提交改动后的整份文档。 */
const document = defineModel<ResumeDocument>({ required: true })

/** 按当前顺序展开的面板行。 */
const rows = computed(() =>
  document.value.section_order.map((section, index) => ({
    section,
    label: SECTION_LABEL[section],
    empty: isSectionEmpty(document.value, section),
    visible: !document.value.hidden_sections.includes(section),
    isFirst: index === 0,
    isLast: index === document.value.section_order.length - 1,
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

/**
 * 提交显隐改动。
 *
 * 参数:
 *     section: 模块。
 *     checked: 开关的新状态；只有严格等于 true 才算"显示"。
 *
 * 注意:
 *     这里按 `unknown` 接收而不是断言成布尔：该组件的类型声明没有出现在自动生成的
 *     `components.d.ts` 里，模板中的事件参数无法推断，写成具体类型只能靠类型断言硬凑。
 *     运行时的实际取值由测试固定（AntDV 的开关提交布尔值）。
 */
function submitVisibility(section: ResumeSection, checked: unknown): void {
  document.value = {
    ...document.value,
    hidden_sections: setSectionHidden(document.value.hidden_sections, section, checked !== true),
  }
}
</script>

<template>
  <a-card size="small" title="模块设置">
    <template #extra>
      <span class="panel-hint">顺序与显隐只影响这份简历</span>
    </template>

    <ul class="section-rows">
      <li
        v-for="row in rows"
        :key="row.section"
        class="section-row"
        :data-testid="`section-row-${row.section}`"
      >
        <span class="section-label">{{ row.label }}</span>
        <span v-if="row.empty" class="section-empty-hint">暂无内容，不会出现在预览中</span>

        <span class="section-actions">
          <a-button
            size="small"
            :disabled="row.isFirst"
            :data-testid="`section-up-${row.section}`"
            @click="submitOrder(row.section, 'up')"
          >
            上移
          </a-button>
          <a-button
            size="small"
            :disabled="row.isLast"
            :data-testid="`section-down-${row.section}`"
            @click="submitOrder(row.section, 'down')"
          >
            下移
          </a-button>
          <a-switch
            :checked="row.visible"
            :data-testid="`section-visibility-${row.section}`"
            @change="submitVisibility(row.section, $event)"
          />
        </span>
      </li>
    </ul>
  </a-card>
</template>

<style scoped>
.section-rows {
  list-style: none;
  margin: 0;
  padding: 0;
}

.section-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.4rem 0;
  border-bottom: 1px solid #f3f4f6;
}

.section-row:last-child {
  border-bottom: none;
}

.section-label {
  min-width: 6rem;
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
  gap: 0.5rem;
  margin-left: auto;
}
</style>
