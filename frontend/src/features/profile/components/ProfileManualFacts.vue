<script setup lang="ts">
/** 手动档案事实：使用导入候选相同的字段区，失焦后按条目自动保存。 */
import { computed, ref, watch } from 'vue'
import {
  educationsApi, experiencesApi, projectsApi, skillsApi,
  type EducationInput, type ExperienceInput, type FactApi, type Profile, type ProjectInput, type SkillInput,
} from '@/shared/api/profile'
import { parseServerError } from '@/shared/forms/serverErrors'
import { PROFILE_FACT_SECTIONS, type ProfileFactField, type ProfileFactKey } from '../profileFormFields'
import ProfileFactSections from './ProfileFactSections.vue'

type FactItem = Record<string, unknown>
type FactRows = Record<ProfileFactKey, FactItem[]>
const props = defineProps<{ profile: Profile | null }>()
const emit = defineEmits<{ changed: []; conflict: [message: string] }>()
const rows = ref<FactRows>({ skills: [], experiences: [], projects: [], educations: [] })
const statuses = ref<Record<string, string>>({})
const errors = ref<Record<string, string>>({})
const saved = new WeakMap<FactItem, string>()
const busy = new WeakSet<FactItem>()

/**
 * 「所属工作经历」下拉的选项。
 *
 * 标签带上月份区间：同一家公司可能有多段任职，只给公司名会让用户选错。时间口径与字段一致（只到月）。
 */
const experienceOptions = computed(() => {
  const active = (props.profile?.experiences ?? []).map((item) => ({
    value: item.id, label: `${item.company} · ${item.title}（${item.start_date.slice(0, 7)} — ${item.end_date?.slice(0, 7) ?? '至今'}）`,
  }))
  const known = new Set(active.map((item) => item.value))
  const retained = (props.profile?.projects ?? []).filter((item) => item.experience_id && !known.has(item.experience_id))
    .map((item) => ({ value: item.experience_id!, label: item.experience_summary ?? '原关联经历（已归档）', disabled: true }))
  return [...active, ...retained]
})


/** 从服务端回填已保存项，同时保留尚未落库或在请求期间继续编辑的草稿。 */
watch(() => props.profile, (profile) => {
  if (profile === null) return
  for (const section of PROFILE_FACT_SECTIONS) {
    const key = section.key
    const local = rows.value[key]
    const pending = local.filter((item) => typeof item['id'] !== 'string')
    const source = profile[key] as unknown as FactItem[]
    const existing = source.map((item) => {
      const draft = local.find((row) => row['id'] === item['id'])
      if (draft && (busy.has(draft) || signature(key, draft) !== saved.get(draft))) {
        draft['version'] = item['version']
        return draft
      }
      const next = { ...item }
      saved.set(next, signature(key, next))
      return next
    })
    rows.value[key] = [...existing, ...pending]
    for (const item of pending) {
      if (complete(key, item)) void saveItem(key, item)
    }
  }
}, { immediate: true })

function signature(key: ProfileFactKey, item: FactItem): string {
  const section = PROFILE_FACT_SECTIONS.find((entry) => entry.key === key)
  return JSON.stringify(section?.fields.map((field) => item[field.name] ?? null) ?? [])
}

function text(item: FactItem, name: string): string {
  const value = item[name]
  return typeof value === 'string' ? value.trim() : ''
}

function optional(item: FactItem, name: string): string | null {
  return text(item, name) || null
}

function complete(key: ProfileFactKey, item: FactItem): boolean {
  const section = PROFILE_FACT_SECTIONS.find((entry) => entry.key === key)
  return section?.fields.every((field) => !field.required || text(item, field.name) !== '') ?? false
}

function apiFor(key: ProfileFactKey): FactApi<FactItem, Record<string, unknown>> {
  const apis = { skills: skillsApi, experiences: experiencesApi, projects: projectsApi, educations: educationsApi }
  return apis[key] as unknown as FactApi<FactItem, Record<string, unknown>>
}

/** 后端各领域仍有独立请求体；仅界面字段共用，隐藏的旧数据随更新保留。 */
function payloadFor(key: ProfileFactKey, item: FactItem): SkillInput | ExperienceInput | ProjectInput | EducationInput {
  if (key === 'skills') return {
    name: text(item, 'name'), category: optional(item, 'category'),
    proficiency: item['proficiency'] as SkillInput['proficiency'] ?? null,
    years_of_experience: optional(item, 'years_of_experience'),
    source_evidence_id: optional(item, 'source_evidence_id'),
    claim_status: item['claim_status'] as SkillInput['claim_status'] ?? 'UNVERIFIED',
  }
  if (key === 'experiences') return {
    company: text(item, 'company'), title: text(item, 'title'), location: optional(item, 'location'),
    start_date: text(item, 'start_date'), end_date: optional(item, 'end_date'),
    responsibilities: optional(item, 'responsibilities'), achievements: optional(item, 'achievements'),
    source_evidence_id: optional(item, 'source_evidence_id'),
  }
  if (key === 'projects') return {
    name: text(item, 'name'), role: optional(item, 'role'), description: optional(item, 'description'),
    achievements: optional(item, 'achievements'), experience_id: optional(item, 'experience_id'),
    tech_stack: Array.isArray(item['tech_stack']) ? item['tech_stack'] as string[] : [],
    url: optional(item, 'url'), start_date: optional(item, 'start_date'), end_date: optional(item, 'end_date'),
    source_evidence_id: optional(item, 'source_evidence_id'),
  }
  return {
    school: text(item, 'school'), major: optional(item, 'major'), degree: optional(item, 'degree'),
    degree_level: item['degree_level'] as EducationInput['degree_level'] ?? null,
    study_mode: item['study_mode'] as EducationInput['study_mode'] ?? null,
    start_date: optional(item, 'start_date'), end_date: optional(item, 'end_date'),
    source_evidence_id: optional(item, 'source_evidence_id'),
  }
}

function addItem(key: ProfileFactKey): void {
  const blank: FactItem = key === 'skills' ? { name: '' }
    : key === 'experiences' ? { company: '', title: '', start_date: '' }
      : key === 'projects' ? { name: '', tech_stack: [] } : { school: '' }
  rows.value[key].push(blank)
}

function updateField(key: ProfileFactKey, index: number, field: ProfileFactField, value: unknown): void {
  const item = rows.value[key][index]
  if (!item) return
  item[field.name] = field.kind === 'tags' ? (Array.isArray(value) ? value : []) : (typeof value === 'string' ? value : null)
  statuses.value[`${key}-${index}`] = '有改动未保存，离开输入框后自动保存'
  delete errors.value[`${key}-${index}-${field.name}`]
}

/** 必填字段未补齐时保留草稿；资料未建档时先等姓名自动创建根记录。 */
async function saveItem(key: ProfileFactKey, item: FactItem): Promise<void> {
  const index = rows.value[key].indexOf(item)
  if (index < 0 || busy.has(item)) return
  const stateKey = `${key}-${index}`
  if (!complete(key, item)) {
    statuses.value[stateKey] = '请先补齐必填项，完成后离开输入框即保存'
    return
  }
  if (props.profile === null) {
    statuses.value[stateKey] = '等待填写姓名并创建档案后保存'
    return
  }
  const currentSignature = signature(key, item)
  if (currentSignature === saved.get(item)) return
  busy.add(item)
  statuses.value[stateKey] = '正在保存…'
  try {
    const api = apiFor(key)
    const payload = payloadFor(key, item) as unknown as Record<string, unknown>
    const id = item['id']
    // 新学历确认字段由本人填写；更新时让后端重新归因，不能用旧摘录给新确认内容背书。
    const updatePayload = { ...payload }
    if (key === 'educations') delete updatePayload['source_evidence_id']
    const persisted = typeof id === 'string'
      ? await api.update(id, { ...updatePayload, version: Number(item['version']) })
      : await api.create(payload)
    if (!rows.value[key].includes(item)) return
    item['id'] = persisted['id']
    item['version'] = persisted['version']
    item['source_evidence_id'] = persisted['source_evidence_id']
    saved.set(item, currentSignature)
    statuses.value[stateKey] = currentSignature === signature(key, item) ? '已保存' : '有新改动待保存'
    emit('changed')
  } catch (cause: unknown) {
    const parsed = parseServerError(cause)
    statuses.value[stateKey] = `保存失败：${parsed.message}${parsed.requestId ? `（错误编号：${parsed.requestId}）` : ''}`
    for (const [name, message] of Object.entries(parsed.fields)) errors.value[`${key}-${index}-${name}`] = message
    if (parsed.code === 'CONFLICT') emit('conflict', parsed.message)
  } finally {
    busy.delete(item)
    if (saved.get(item) === currentSignature && signature(key, item) !== currentSignature) void saveItem(key, item)
  }
}

function onBlur(key: ProfileFactKey, index: number): void {
  const item = rows.value[key][index]
  if (item) void saveItem(key, item)
}

async function removeItem(key: ProfileFactKey, index: number): Promise<void> {
  const item = rows.value[key][index]
  if (!item || busy.has(item)) return
  const id = item['id']
  if (typeof id !== 'string') {
    rows.value[key].splice(index, 1)
    return
  }
  statuses.value[`${key}-${index}`] = '正在归档…'
  try {
    await apiFor(key).remove(id, Number(item['version']))
    rows.value[key].splice(index, 1)
    emit('changed')
  } catch (cause: unknown) {
    const parsed = parseServerError(cause)
    statuses.value[`${key}-${index}`] = `归档失败：${parsed.message}`
  }
}
</script>

<template>
  <ProfileFactSections :items="rows" mode="manual" :source-titles="Object.fromEntries((profile?.evidences ?? []).map((evidence) => [evidence.id, evidence.title]))" :statuses="statuses" :errors="errors" :experience-options="experienceOptions" @update-field="updateField" @field-blur="onBlur" @add-item="addItem" @remove-item="removeItem" />
</template>
