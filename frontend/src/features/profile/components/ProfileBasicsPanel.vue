<script setup lang="ts">
/**
 * 档案根信息面板。
 *
 * 同时承担"首次创建"：档案尚未创建时后端对 `GET /profile` 返回 404，此时同一个表单改用
 * `POST /profile` 提交（不带乐观锁版本号）。做成一个组件而不是两个，是因为字段完全相同，
 * 分成两份迟早会出现"创建表单能填城市、编辑表单漏了"这类不一致。
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
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

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

interface LinkDraft {
  label: string
  url: string
}

const fullName = ref('')
const headline = ref('')
const summary = ref('')
const email = ref('')
const phone = ref('')
const city = ref('')
const links = ref<LinkDraft[]>([])
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

/** 用当前档案重置表单；`profile` 变化（例如冲突后重新加载）时同步覆盖，避免界面显示旧值。 */
watch(
  () => props.profile,
  (profile) => {
    fullName.value = profile?.full_name ?? ''
    headline.value = profile?.headline ?? ''
    summary.value = profile?.summary ?? ''
    email.value = profile?.email ?? ''
    phone.value = profile?.phone ?? ''
    city.value = profile?.city ?? ''
    links.value = (profile?.links ?? []).map((link) => ({ label: link.label, url: link.url }))
    fieldErrors.value = {}
    linksError.value = null
    panelError.value = null
  },
  { immediate: true },
)

function addLink(): void {
  links.value = [...links.value, { label: '', url: '' }]
}

function removeLink(index: number): void {
  links.value = links.value.filter((_, current) => current !== index)
}

/** 整行留空视为"用户只是点开了输入框"，不参与提交。 */
function meaningfulLinks(): LinkDraft[] {
  return links.value.filter((link) => link.label.trim() !== '' || link.url.trim() !== '')
}

async function submit(): Promise<void> {
  fieldErrors.value = {}
  linksError.value = null
  panelError.value = null

  const incomplete = meaningfulLinks().filter((link) => link.label.trim() === '' || link.url.trim() === '')
  if (incomplete.length > 0) {
    linksError.value = '每条链接都需要同时填写名称与地址；留空的整行会被忽略。'
    return
  }

  if (fullName.value.trim() === '') {
    fieldErrors.value = { full_name: '该项为必填。' }
    return
  }

  saving.value = true
  try {
    const payloadLinks: ProfileLink[] = meaningfulLinks().map((link) => ({
      label: link.label.trim(),
      url: link.url.trim(),
    }))
    if (props.profile === null) {
      const payload: ProfileCreateInput = {
        full_name: fullName.value.trim(),
        headline: emptyToNull(headline.value),
        summary: emptyToNull(summary.value),
        email: emptyToNull(email.value),
        phone: emptyToNull(phone.value),
        city: emptyToNull(city.value),
        links: payloadLinks,
      }
      await createProfile(payload)
    } else {
      const payload: ProfileBasicsInput = {
        version: props.profile.version,
        full_name: fullName.value.trim(),
        headline: emptyToNull(headline.value),
        summary: emptyToNull(summary.value),
        email: emptyToNull(email.value),
        phone: emptyToNull(phone.value),
        city: emptyToNull(city.value),
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
  panelError.value = parsed
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

    <a-form layout="vertical">
      <a-form-item
        label="姓名"
        :help="fieldErrors['full_name'] ?? '用于简历与投递材料，请填真实姓名。'"
        :validate-status="fieldErrors['full_name'] === undefined ? undefined : 'error'"
      >
        <a-input :value="fullName" :maxlength="100" allow-clear @update:value="(value: unknown) => (fullName = String(value))" />
      </a-form-item>

      <a-form-item
        label="一句话头衔"
        :help="fieldErrors['headline']"
        :validate-status="fieldErrors['headline'] === undefined ? undefined : 'error'"
      >
        <a-input :value="headline" :maxlength="200" allow-clear @update:value="(value: unknown) => (headline = String(value))" />
      </a-form-item>

      <a-form-item
        label="个人简介"
        :help="fieldErrors['summary']"
        :validate-status="fieldErrors['summary'] === undefined ? undefined : 'error'"
      >
        <a-textarea :value="summary" :rows="3" allow-clear @update:value="(value: unknown) => (summary = String(value))" />
      </a-form-item>

      <a-row :gutter="16">
        <a-col :span="12">
          <a-form-item
            label="邮箱"
            :help="fieldErrors['email']"
            :validate-status="fieldErrors['email'] === undefined ? undefined : 'error'"
          >
            <a-input :value="email" :maxlength="320" allow-clear @update:value="(value: unknown) => (email = String(value))" />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item
            label="手机"
            :help="fieldErrors['phone']"
            :validate-status="fieldErrors['phone'] === undefined ? undefined : 'error'"
          >
            <a-input :value="phone" :maxlength="50" allow-clear @update:value="(value: unknown) => (phone = String(value))" />
          </a-form-item>
        </a-col>
      </a-row>

      <a-form-item
        label="所在城市"
        :help="fieldErrors['city']"
        :validate-status="fieldErrors['city'] === undefined ? undefined : 'error'"
      >
        <a-input :value="city" :maxlength="100" allow-clear @update:value="(value: unknown) => (city = String(value))" />
      </a-form-item>

      <a-form-item label="公开链接" :help="linksError ?? '例如 GitHub、博客；留空的整行会被忽略。'">
        <div v-for="(link, index) in links" :key="index" class="link-row">
          <a-input v-model:value="link.label" :maxlength="50" placeholder="名称（如 GitHub）" />
          <a-input v-model:value="link.url" :maxlength="2048" placeholder="https://…" />
          <a-button type="link" danger @click="removeLink(index)">移除</a-button>
        </div>
        <a-button type="dashed" block @click="addLink">添加链接</a-button>
      </a-form-item>

      <a-button type="primary" :loading="saving" data-testid="save-basics" @click="submit">
        {{ isCreate ? '创建档案' : '保存' }}
      </a-button>
    </a-form>
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

.link-row {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
</style>
