<script setup lang="ts">
/**
 * 档案根信息面板。
 *
 * 同时承担"首次创建"：档案尚未创建时后端对 `GET /profile` 返回 404，此时同一个表单改用
 * `POST /profile` 提交（不带乐观锁版本号）。做成一个组件而不是两个，是因为字段完全相同，
 * 分成两份迟早会出现"创建表单能填城市、编辑表单漏了"这类不一致。
 *
 * **离开输入框即自动保存**：创建与编辑两处都不再提供保存按钮。档案页是长期维护的界面，
 * 每改一个字段都要去找一次按钮，用户真正担心的是"我改了到底存没存"，而不是少点一次按钮——
 * 因此这里把状态显式呈现出来（正在保存／有改动未保存／已保存），并且：
 * - 没有改动不发请求（失焦很频繁，空请求只是浪费往返）；
 * - 姓名留空、链接只填一半时**先不保存**并就地提示（这两种状态提交上去只会失败）；
 * - 保存失败就地给出原因，字段级错误落到对应输入框，绝不静默丢弃用户的输入。
 *
 * 字段仍按 `basicsFields.ts` 的共享定义渲染：导入候选核对页用的是同一份定义与同一个布局组件
 * （`ProfileBasicsSection`），因此两处的字段顺序、标签、帮助文本与网格不可能漂移。
 *
 * 公开链接是唯一的数组字段，用可增删的行内输入维护；**整行留空即忽略**（因此新增一个空行不会
 * 触发保存），只填一半则先不保存，等这一行填完再说。
 */

import { computed, nextTick, ref, watch } from 'vue'

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
import { focusFormTarget, notifyFormIssue } from '@/shared/feedback/formNotice'
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
/**
 * 最近已知的乐观锁版本。
 *
 * 保存响应会返回新版本，必须立刻记住：否则"保存成功 → 页面还没重新加载 → 用户又改了一个字段"
 * 这串动作会拿着旧版本号提交，被后端 409 拒绝，用户看到的是一次莫名其妙的冲突。
 */
const version = ref<number | null>(null)
/** 最近一次保存（或从服务端加载）后的表单快照；用于判断有没有需要保存的改动。 */
const savedSnapshot = ref('')
/** 是否已经用服务端的值回填过一次；首次挂载必须回填，不能被"脏检查"挡住。 */
let initialised = false

const isCreate = computed(() => props.profile === null)

function basicTarget(name: string): HTMLElement | null {
  if (!BASIC_FIELDS.some((field) => field.name === name)) return null
  return document.querySelector<HTMLElement>(`[data-testid="panel-basics"] [data-testid="basics-${name}"]`)
}

/** 表单旁保留原有错误文案；首次校验失败时自动定位，通知只负责提醒。 */
async function showBasicIssue(title: string, detail: string, target: () => HTMLElement | null): Promise<void> {
  await nextTick()
  focusFormTarget(target())
  notifyFormIssue({ kind: 'warning', title, detail, key: 'profile-basics-warning' })
}

const title = '档案与联系方式'

const description = computed(() =>
  isCreate.value
    ? '首次填写档案根信息：填好姓名后离开输入框即自动创建。V1 只允许一份主档案，因此创建后不再提供第二个入口。'
    : '联系方式只保存在本地数据库；日志与 AI 提示词不会无条件输出它们（见 docs/data-model.md 3.1）。'
      + '改动在离开输入框时自动保存，不需要点保存按钮。',
)

/** 表单当前形态；与最近一次保存的快照比较，决定"有没有需要保存的改动"。 */
function snapshot(): string {
  return JSON.stringify([
    BASIC_FIELDS.map((field) => text(field.name).trim()),
    submittableLinks(links.value),
  ])
}

/** 有未保存的改动吗？没有就不发请求——失焦很频繁，空请求只会浪费一次往返。 */
const dirty = computed(() => snapshot() !== savedSnapshot.value)

/** 保存状态机：创建模式在填好姓名前还谈不上"已保存"，因此单独一个状态。 */
const saveState = computed<'saving' | 'awaiting-name' | 'dirty' | 'saved'>(() => {
  if (saving.value) return 'saving'
  if (isCreate.value && text('full_name').trim() === '') return 'awaiting-name'
  return dirty.value ? 'dirty' : 'saved'
})

/**
 * 保存状态文案。
 *
 * 自动保存最大的风险是"用户不知道到底存没存"，因此状态必须一直可见，而不是只在出错时出现。
 */
const saveStateText = computed(() => {
  if (saveState.value === 'saving') return '正在保存…'
  if (saveState.value === 'awaiting-name') return '填写姓名后离开输入框即自动创建档案'
  if (saveState.value === 'dirty') return '有改动尚未保存：请按提示补全或修正后再次离开输入框'
  return '已保存（离开输入框即自动保存）'
})

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

/**
 * 用当前档案重置表单；`profile` 变化（例如保存后重新加载）时同步覆盖，避免界面显示旧值。
 *
 * 例外：本地有未保存的改动时不覆盖草稿——用户可能正在输入，而这次刷新只是上一次保存的回声；
 * 那种情况下只更新版本号，草稿留给下一次失焦提交。
 */
watch(
  () => props.profile,
  (profile) => {
    version.value = profile?.version ?? null
    if (initialised && dirty.value) return
    const next: Record<string, string> = {}
    for (const field of BASIC_FIELDS) {
      next[field.name] = profile?.[field.name] ?? ''
    }
    values.value = next
    links.value = (profile?.links ?? []).map((link) => ({ label: link.label, url: link.url }))
    savedSnapshot.value = snapshot()
    initialised = true
    fieldErrors.value = {}
    linksError.value = null
    panelError.value = null
  },
  { immediate: true },
)

function setValue(name: BasicFieldName, value: unknown): void {
  values.value[name] = typeof value === 'string' ? value : ''
}

/**
 * 链接行变化。
 *
 * 整行增删是明确动作，立刻保存（新增的空行会被 `submittableLinks` 过滤掉，因此不会白跑一次
 * 请求）；行内输入只是打字，交给失焦时保存，避免每敲一个字都发一次 PATCH。
 */
function onLinksUpdate(next: ProfileLink[]): void {
  const structural = next.length !== links.value.length
  links.value = next
  if (structural) void saveIfDirty()
}

/**
 * 有改动就保存；没有改动不发请求，校验未通过则先不保存并给出字段级提示。
 *
 * 为什么整份表单一起提交，而不是只提交失焦的那个字段：接口本身就是整份根信息替换
 * （`ProfileBasicsInput`），只提交单个字段反而要额外维护"哪些字段已确认"的状态，
 * 而这份表单只有 6 个短字段。
 */
async function saveIfDirty(): Promise<void> {
  if (saving.value || !dirty.value) return
  fieldErrors.value = {}
  linksError.value = null
  panelError.value = null

  // 只填一半的链接意图不明：先不保存，等这一行填完整（草稿留在输入框里，不会丢）。
  if (incompleteLinks(links.value).length > 0) {
    linksError.value = '每条链接都需要同时填写名称与地址；留空的整行会被忽略。'
    const index = links.value.findIndex((link) =>
      (link.label.trim() !== '' || link.url.trim() !== '') && (link.label.trim() === '' || link.url.trim() === ''),
    )
    const name = links.value[index]?.label.trim() === '' ? 'label' : 'url'
    await showBasicIssue('请补全公开链接', linksError.value, () => document.querySelector<HTMLElement>(`[data-testid="panel-basics"] [data-testid="link-${name}-${index}"]`))
    return
  }

  const fullName = text('full_name').trim()
  if (fullName === '') {
    // 姓名是必填锚点：既不能据此创建档案，也不能把已有档案改成没有姓名。
    fieldErrors.value = { full_name: '该项为必填。' }
    await showBasicIssue('请填写姓名', '姓名是创建和保存个人档案的必填项。', () => basicTarget('full_name'))
    return
  }

  // 先记下这次要提交的形态：等待响应期间用户可能继续输入，成功后不能把新输入误标成已保存。
  const signature = snapshot()
  saving.value = true
  try {
    const payloadLinks = submittableLinks(links.value)
    let saved: Profile
    if (props.profile === null) {
      const payload: ProfileCreateInput = {
        full_name: fullName,
        headline: emptyToNull(text('headline')),
        summary: emptyToNull(text('summary')),
        email: emptyToNull(text('email')),
        phone: emptyToNull(text('phone')),
        city: emptyToNull(text('city')),
        links: payloadLinks,
      }
      saved = await createProfile(payload)
    } else {
      const payload: ProfileBasicsInput = {
        version: version.value ?? props.profile.version,
        full_name: fullName,
        headline: emptyToNull(text('headline')),
        summary: emptyToNull(text('summary')),
        email: emptyToNull(text('email')),
        phone: emptyToNull(text('phone')),
        city: emptyToNull(text('city')),
        links: payloadLinks,
      }
      saved = await saveProfileBasics(payload)
    }
    savedSnapshot.value = signature
    version.value = saved.version
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
  } else {
    notifyFormIssue({ kind: 'error', title: '保存基本资料失败', detail: parsed.message, key: 'profile-basics-error' })
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
    <template #extra><slot name="header-extra" /></template>
    <p class="panel-description">{{ description }}</p>

    <p v-if="panelError" class="form-error-summary" role="alert" data-testid="error-basics">{{ panelError.message }} {{ alertDescription }}</p>

    <!-- 基本信息字段与布局来自共享组件：与导入候选核对页是同一套定义、同一套网格。 -->
    <ProfileBasicsSection
      :fields="BASIC_FIELDS"
      :record="values"
      :errors="fieldErrors"
      testid-prefix="basics"
      @update-field="setValue"
      @field-blur="saveIfDirty"
    >
      <!-- 公开链接与候选核对页是同一个组件：行结构、帮助文本与“整行留空”的处理只有一份。 -->
      <ProfileLinksField
        :links="links"
        :error="linksError"
        @update-links="onLinksUpdate"
        @field-blur="saveIfDirty"
      />
    </ProfileBasicsSection>
    <slot />

    <!--
      保存状态：不再有保存按钮，因此"到底存没存"必须由这一行回答。
      危险色只用于需要用户处理的状态（有改动未保存），避免每次输入都红一下。
    -->
    <p class="save-status" :data-state="saveState" data-testid="basics-save-status">
      {{ saveStateText }}
    </p>
  </a-card>
</template>

<style scoped>
.form-error-summary { color: var(--ja-color-danger); font-size: 13px; line-height: 1.6; }
.basics-panel {
  margin-bottom: 1rem;
}

.panel-description {
  color: #6b7280;
  margin-bottom: 0.75rem;
}

/* 保存状态：与卡片描述同级的小字，始终可见。 */
.save-status {
  margin: 0;
  color: #6b7280;
  font-size: 12px;
  line-height: 1.6;
}

/* 需要用户处理的状态用危险色：自动保存不能把"没存上"藏成一行灰色小字。 */
.save-status[data-state='dirty'] {
  color: var(--ja-color-danger);
}
</style>
