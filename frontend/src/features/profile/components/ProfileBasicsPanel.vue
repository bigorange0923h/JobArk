<script setup lang="ts">
/**
 * 档案根信息面板。
 *
 * 同时承担"首次创建"：档案尚未创建时后端对 `GET /profile` 返回 404，此时同一个表单改用
 * `POST /profile` 提交（不带乐观锁版本号）。做成一个组件而不是两个，是因为字段完全相同，
 * 分成两份迟早会出现"创建表单能填城市、编辑表单漏了"这类不一致。
 *
 * 字段不再在本文件里逐个书写，而是按 `basicsFields.ts` 的共享定义渲染：导入候选核对页用的是
 * 同一份定义（取其子集），因此两处的字段顺序、标签与帮助文本不可能漂移。布局复用
 * `theme.css` 的 `.profile-field-grid`（桌面端每行最多两个普通字段、长文本独占一行、窄屏单列）。
 *
 * 公开链接是唯一的数组字段，用可增删的行内输入维护；**整行留空即忽略**，只填一半则在前端拦下，
 * 因为那种情况下用户意图不明，而提交上去只会得到一条难懂的嵌套字段错误。
 */

import { computed, ref, watch } from 'vue'

import { ApiError } from '@/shared/api/client'
import {
  createProfile,
  saveProfileBasics,
  type Profile,
  type ProfileBasicsInput,
  type ProfileCreateInput,
  type ProfileLink,
} from '@/shared/api/profile'
import { isGlobalFailure, notifyFailure } from '@/shared/feedback/failureNotice'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import { BASIC_FIELDS, type BasicFieldName } from '../basicsFields'
import { incompleteLinks, submittableLinks } from '../links'
import ProfileBasicsSection from './ProfileBasicsSection.vue'
import ProfileLinksField from './ProfileLinksField.vue'

const props = defineProps<{
  /** 当前档案；为 null 表示尚未创建。 */
  profile: Profile | null
}>()

const emit = defineEmits<{
  /** 保存成功，页面应重新加载档案聚合。 */
  changed: []
  /** 版本过期等需要刷新才能继续的冲突。 */
  conflict: [message: string]
}>()

/** 字段名 → 输入框文本；空字符串代表"未填写"，提交时统一转为 null。 */
const values = ref<Record<string, string>>({})
/** 公开链接草稿；行内允许留空，提交前由共享规则过滤与校验。 */
const links = ref<ProfileLink[]>([])
const fieldErrors = ref<Record<string, string>>({})
const linksError = ref<string | null>(null)
const panelError = ref<ParsedServerError | null>(null)
const saving = ref(false)

const isCreate = computed(() => props.profile === null)

const title = computed(() => (isCreate.value ? '创建个人档案' : '档案与联系方式'))

const description = computed(() =>
  isCreate.value
    ? '首次填写档案根信息。V1 只允许一份主档案，因此创建后不再提供第二个入口。'
    : '联系方式只保存在本地数据库；日志与 AI 提示词不会无条件输出它们（见 docs/data-model.md 3.1）。',
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

/** 读取一个字段的当前文本；缺省为空字符串。 */
function text(name: BasicFieldName): string {
  return values.value[name] ?? ''
}

/** 用当前档案重置表单；`profile` 变化（例如冲突后重新加载）时同步覆盖，避免界面显示旧值。 */
watch(
  () => props.profile,
  (profile) => {
    const next: Record<string, string> = {}
    for (const field of BASIC_FIELDS) {
      next[field.name] = profile?.[field.name] ?? ''
    }
    values.value = next
    links.value = (profile?.links ?? []).map((link) => ({ label: link.label, url: link.url }))
    fieldErrors.value = {}
    linksError.value = null
    panelError.value = null
  },
  { immediate: true },
)

function setValue(name: BasicFieldName, value: unknown): void {
  values.value[name] = typeof value === 'string' ? value : ''
}

async function submit(): Promise<void> {
  fieldErrors.value = {}
  linksError.value = null
  panelError.value = null

  if (incompleteLinks(links.value).length > 0) {
    linksError.value = '每条链接都需要同时填写名称与地址；留空的整行会被忽略。'
    return
  }

  if (text('full_name').trim() === '') {
    fieldErrors.value = { full_name: '该项为必填。' }
    return
  }

  saving.value = true
  try {
    const payloadLinks = submittableLinks(links.value)
    if (props.profile === null) {
      const payload: ProfileCreateInput = {
        full_name: text('full_name').trim(),
        headline: emptyToNull(text('headline')),
        summary: emptyToNull(text('summary')),
        email: emptyToNull(text('email')),
        phone: emptyToNull(text('phone')),
        city: emptyToNull(text('city')),
        links: payloadLinks,
      }
      await createProfile(payload)
    } else {
      const payload: ProfileBasicsInput = {
        version: props.profile.version,
        full_name: text('full_name').trim(),
        headline: emptyToNull(text('headline')),
        summary: emptyToNull(text('summary')),
        email: emptyToNull(text('email')),
        phone: emptyToNull(text('phone')),
        city: emptyToNull(text('city')),
        links: payloadLinks,
      }
      await saveProfileBasics(payload)
    }
    emit('changed')
  } catch (error: unknown) {
    handleError(error)
  } finally {
    saving.value = false
  }
}

function handleError(error: unknown): void {
  const parsed = parseServerError(error)
  fieldErrors.value = parsed.fields
  // 字段错误、版本冲突与"档案已被删除"必须留在表单上下文里；只有无法定位字段的失败
  // （网络、超时、服务端错误）改为全局通知，避免卡片上方插一块与当前输入无关的错误。
  const global = isGlobalFailure(parsed)
  panelError.value = global ? null : parsed
  if (global) {
    notifyFailure(parsed, '保存基本资料')
  }
  if (parsed.code === 'CONFLICT' && parsed.fields['version'] !== undefined) {
    emit('conflict', parsed.message)
  } else if (error instanceof ApiError && parsed.code === 'RESOURCE_NOT_FOUND') {
    // 档案在编辑期间被删除或不存在：需要重新加载以回到"创建"入口。
    emit('conflict', parsed.message)
  }
}

function emptyToNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}
</script>

<template>
  <a-card :bordered="false" class="basics-panel" data-testid="panel-basics">
    <template #title>{{ title }}</template>
    <p class="panel-description">{{ description }}</p>

    <a-alert
      v-if="panelError"
      type="error"
      show-icon
      class="panel-alert"
      :message="panelError.message"
      :description="alertDescription"
      data-testid="error-basics"
    />

    <!-- 基本信息字段与布局来自共享组件：与导入候选核对页是同一套定义、同一套网格。 -->
    <ProfileBasicsSection
      :fields="BASIC_FIELDS"
      :record="values"
      :errors="fieldErrors"
      @update-field="setValue"
    >
      <!-- 公开链接与候选核对页是同一个组件：行结构、帮助文本与“整行留空”的处理只有一份。 -->
      <ProfileLinksField :links="links" :error="linksError" @update-links="links = $event" />

      <a-form-item class="profile-field-grid__wide">
        <a-button type="primary" :loading="saving" data-testid="save-basics" @click="submit">
          {{ isCreate ? '创建档案' : '保存' }}
        </a-button>
      </a-form-item>
    </ProfileBasicsSection>
  </a-card>
</template>

<style scoped>
.basics-panel {
  margin-bottom: 1rem;
}

.panel-description {
  color: #6b7280;
  margin-bottom: 0.75rem;
}

.panel-alert {
  margin-bottom: 1rem;
}
</style>
