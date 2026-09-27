<script setup lang="ts">
/**
 * 公开链接编辑区：创建/编辑档案页与导入候选核对页共用同一个组件、同一段帮助文本。
 *
 * 数组由父组件持有，本组件不复制状态：每次编辑都按不可变方式生成新数组再冒泡，
 * 因此父组件永远能看到自己那份数据，也不会出现两个组件各改一半。
 * `disabled` 用于“已有档案时导入不覆盖既有链接”这类场景——字段仍然可见（用户能看到契约形状），
 * 但不可编辑，避免填了却被静默丢弃。
 */

import type { ProfileLink } from '@/shared/api/profile'

const props = withDefaults(
  defineProps<{
    links: readonly ProfileLink[]
    /** 字段级错误文案；未提供时显示默认帮助文本。 */
    error?: string | null
    /** 是否禁用编辑（链接仍完整显示）。 */
    disabled?: boolean
  }>(),
  { error: null, disabled: false },
)

const emit = defineEmits<{
  updateLinks: [links: ProfileLink[]]
  /** 链接行失焦；档案页据此自动保存，候选核对页不处理（候选要等确认才落库）。 */
  fieldBlur: []
}>()

/** 复制一份再改：父组件持有的数组不被就地修改，避免两份视图同时写同一份数据。 */
function copy(): ProfileLink[] {
  return props.links.map((link) => ({ label: link.label, url: link.url }))
}

function replace(index: number, patch: Partial<ProfileLink>): void {
  emit(
    'updateLinks',
    copy().map((link, current) => (current === index ? { ...link, ...patch } : link)),
  )
}

function add(): void {
  emit('updateLinks', [...copy(), { label: '', url: '' }])
}

function remove(index: number): void {
  emit(
    'updateLinks',
    copy().filter((_, current) => current !== index),
  )
}
</script>

<template>
  <a-form-item
    label="公开链接"
    class="profile-field-grid__wide"
    :help="error ?? '例如 GitHub、博客；留空的整行会被忽略。'"
    :validate-status="error === null ? undefined : 'error'"
  >
    <div v-for="(link, index) in props.links" :key="index" class="link-row">
      <a-input
        :value="link.label"
        :disabled="disabled"
        :maxlength="50"
        placeholder="名称（如 GitHub）"
        :data-testid="`link-label-${index}`"
        @update:value="(value: unknown) => replace(index, { label: typeof value === 'string' ? value : '' })"
        @blur="emit('fieldBlur')"
      />
      <a-input
        :value="link.url"
        :disabled="disabled"
        :maxlength="2048"
        placeholder="https://…"
        :data-testid="`link-url-${index}`"
        @update:value="(value: unknown) => replace(index, { url: typeof value === 'string' ? value : '' })"
        @blur="emit('fieldBlur')"
      />
      <a-button type="link" danger :disabled="disabled" :data-testid="`remove-link-${index}`" @click="remove(index)">
        移除
      </a-button>
    </div>
    <a-button type="dashed" block :disabled="disabled" data-testid="add-link" @click="add">添加链接</a-button>
  </a-form-item>
</template>

<style scoped>
.link-row {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
</style>
