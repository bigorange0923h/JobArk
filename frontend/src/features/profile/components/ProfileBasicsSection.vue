<script setup lang="ts">
/**
 * 基本信息字段区：创建/编辑档案页与导入候选核对页共用的**唯一**布局组件。
 *
 * 两边都必须用本组件渲染基本信息，而不是各写一份相似模板。字段顺序、标签、帮助文本、
 * 必填标记、控件类型与网格布局全部来自 `basicsFields.ts` 与 `theme.css` 的 `.profile-field-grid`
 * （桌面端每行最多两个普通字段、长文本独占一行、窄屏单列），因此不会出现
 * “创建时能填个人简介、核对时漏了”这类两边各自演化的漂移。
 *
 * 组件自身不持有状态：取值由 `record` 传入（字段名 → 值），改动通过 `update-field` 冒泡。
 * 空值与非法类型一律渲染为**空输入框**——既不伪造默认值，也不因留空而隐藏字段。
 *
 * `record` 声明为 `object` 而不是 `Record<string, unknown>`：调用方传的是候选/表单这类有具体
 * 字段的接口类型，而 TypeScript 不允许把没有索引签名的接口赋给 `Record<string, unknown>`。
 * 组件只按字段名读取字符串、读不到就按空处理，因此内部这一次收窄是安全的。
 */

import type { BasicField, BasicFieldName } from '../basicsFields'
import ProfileCityField from './ProfileCityField.vue'

const props = withDefaults(
  defineProps<{
    /** 要渲染的字段；顺序即渲染顺序（创建页传全集，候选页传候选契约支持的子集）。 */
    fields: readonly BasicField[]
    /** 取值来源：字段名 → 值；非字符串值按未填写处理。 */
    record: object | null
    /** 字段级错误文案；未提供时回落到字段自身的帮助文本。 */
    errors?: Record<string, string>
    /** 区块标题；两侧使用同一标题，视觉上才是同一个区块。 */
    title?: string
    /** 输入框 testId 前缀（最终为 `${前缀}-${字段名}`）；不传则不输出 testId 属性。 */
    testidPrefix?: string
    /**
     * 只读字段：仍然渲染（字段形状可见），但不可编辑。
     *
     * 用于“已有档案时导入不覆盖既有基本信息”这类场景；禁用而不是隐藏，避免用户以为字段消失了，
     * 也避免填进去的内容被静默丢弃。
     */
    disabledFields?: readonly string[]
  }>(),
  { errors: () => ({}), title: '基本信息', testidPrefix: '', disabledFields: () => [] },
)

const emit = defineEmits<{
  /** 字段值变化；空值以空字符串上报，由持有者决定写 null 还是保留。 */
  updateField: [name: BasicFieldName, value: string]
  /**
   * 字段失焦。
   *
   * 档案页据此自动保存（离开输入框即落库）；候选核对页不处理它——候选要等用户确认后才写入，
   * 这一点由持有者决定，组件只负责如实上报"这个字段失焦了"。
   */
  fieldBlur: [name: BasicFieldName]
}>()

/** 读取字段文本；缺失或非字符串都按“未填写”处理。 */
function textOf(name: BasicFieldName): string {
  const value = (props.record as Record<string, unknown> | null)?.[name]
  return typeof value === 'string' ? value : ''
}

/** 字段 testId；未配置前缀时返回 undefined，属性不会被渲染出来。 */
function testidOf(name: BasicFieldName): string | undefined {
  return props.testidPrefix === '' ? undefined : `${props.testidPrefix}-${name}`
}

function onUpdate(name: BasicFieldName, value: unknown): void {
  emit('updateField', name, typeof value === 'string' ? value : '')
}
</script>

<template>
  <section class="basics-section">
    <h3 v-if="title !== ''" class="basics-section__title">{{ title }}</h3>
    <a-form layout="vertical" class="profile-field-grid">
      <a-form-item
        v-for="field in fields"
        :key="field.name"
        :label="field.label"
        :class="{ 'profile-field-grid__wide': field.wide }"
        :required="field.required"
        :help="errors[field.name] ?? field.help"
        :validate-status="errors[field.name] === undefined ? undefined : 'error'"
      >
        <ProfileCityField
          v-if="field.kind === 'city'"
          :value="textOf(field.name)"
          :disabled="disabledFields.includes(field.name)"
          :max-length="field.maxLength"
          :testid="testidOf(field.name)"
          @update-value="(value: string) => onUpdate(field.name, value)"
          @blur="emit('fieldBlur', field.name)"
        />
        <a-textarea
          v-else-if="field.kind === 'textarea'"
          :value="textOf(field.name)"
          :rows="3"
          :maxlength="field.maxLength"
          :placeholder="field.placeholder"
          :disabled="disabledFields.includes(field.name)"
          :data-testid="testidOf(field.name)"
          allow-clear
          @update:value="(value: unknown) => onUpdate(field.name, value)"
          @blur="emit('fieldBlur', field.name)"
        />
        <a-input
          v-else
          :value="textOf(field.name)"
          :maxlength="field.maxLength"
          :placeholder="field.placeholder"
          :disabled="disabledFields.includes(field.name)"
          :data-testid="testidOf(field.name)"
          allow-clear
          @update:value="(value: unknown) => onUpdate(field.name, value)"
          @blur="emit('fieldBlur', field.name)"
        />
      </a-form-item>

      <!-- 调用方追加的表单项（创建页的公开链接与提交按钮）留在这里，保持同属一个字段网格。 -->
      <slot />
    </a-form>
  </section>
</template>

<style scoped>
/* 标题与候选页其它分区标题（`.candidate-section h3`）保持一致：两边是同一个区块，视觉不能分家。 */
.basics-section__title {
  margin: 0 0 10px;
  font-size: 15px;
}
</style>
