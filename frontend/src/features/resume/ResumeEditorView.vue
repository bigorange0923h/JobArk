<script setup lang="ts">
/**
 * 候选稿编辑器：结构化编辑一份简历文档。
 *
 * 三条与后端契约直接相关的规则：
 *
 * - **保存提交整份文档 + 当前版本号**。文档是自包含整体，只提交改动过的字段无法表达"删掉一条
 *   经历"，而增量合并还需要在服务端定义每一层的合并语义——那正是文档被当作整体处理要避免的事。
 * - **保存成功后采用响应里的新版本号**。后端每次写入都自增版本，若仍拿旧版本号，下一次保存必然
 *   因版本过期失败，用户看到的却是"点了保存没反应"。
 * - **字段级错误定位到条目**。后端给出的路径形如 `skills.0.source_fact_id`；界面据此在对应条目上
 *   标出原因，而不是只弹一句"文档非法"——那句话无法回答"到底哪一条有问题"。
 *
 * 编辑只改候选稿：版本不可变，确认候选稿才会产生新版本。
 */

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { PlusOutlined } from '@ant-design/icons-vue'

import { fetchProfile, type Profile } from '@/shared/api/profile'
import {
  fetchDraft,
  updateDraft,
  type ResumeDocument,
  type ResumeDraft,
  type ResumeEducationItem,
  type ResumeExperienceItem,
  type ResumeLanguageItem,
  type ResumeProjectItem,
  type ResumeSection,
  type ResumeSkillItem,
} from '@/shared/api/resume'
import { isGlobalFailure, notifyFailure } from '@/shared/feedback/failureNotice'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'
import { skillCategoryOptions as buildSkillCategoryOptions } from '@/shared/skillCategories'

import SectionSettingsPanel from './components/SectionSettingsPanel.vue'
import ResumePreview from './components/ResumePreview.vue'
import DegreeField from '../profile/components/DegreeField.vue'
import {
  SECTION_LABEL, createBlankDocument, isSectionEmpty,
  resumeEducationFromProfile, resumeExperienceFromProfile, resumeLanguageFromProfile,
  resumeProjectFromProfile, resumeSkillFromProfile, sectionDocumentKey, toLines,
} from './document'

const props = defineProps<{ resumeId: string; draftId: string }>()

const router = useRouter()

/** 正在编辑的文档；始终是有效对象，使模板不必到处判空。 */
const document = ref<ResumeDocument>(createBlankDocument())
const draft = ref<ResumeDraft | null>(null)
const profile = ref<Profile | null>(null)
const loaded = ref(false)
const loading = ref(false)
const saving = ref(false)
const templateOpen = ref(false)
const saveFailed = ref(false)
let saveTimer: ReturnType<typeof setTimeout> | null = null
const loadError = ref<ParsedServerError | null>(null)
const actionError = ref<ParsedServerError | null>(null)
const photoError = ref<string | null>(null)
const fieldErrors = ref<Record<string, string>>({})
/** 最近一次与服务端一致的文档快照；用于判断"有没有改动"，避免无意义的往返与版本自增。 */
const savedSnapshot = ref('')

const dirty = computed(() => JSON.stringify(document.value) !== savedSnapshot.value)
const saveStatus = computed(() => {
  if (saving.value) return '正在保存…'
  if (saveFailed.value) return '保存失败，修改后将重试'
  return dirty.value ? '有改动待保存' : '已自动保存'
})

const fieldErrorList = computed(() =>
  Object.entries(fieldErrors.value).map(([path, reason]) => ({ path, reason })),
)

/** 每类事实的可选来源：空值表示"手写，没有来源"。 */
const skillOptions = computed(() => toOptions(profile.value?.skills, (item) => item.name))
const experienceOptions = computed(() =>
  toOptions(profile.value?.experiences, (item) => `${item.company} · ${item.title}`),
)
const projectOptions = computed(() => toOptions(profile.value?.projects, (item) => item.name))
const educationOptions = computed(() => toOptions(profile.value?.educations, (item) => item.school))
const languageOptions = computed(() => toOptions(profile.value?.languages, (item) => item.language))
/** 常用选项之外保留当前文档和档案中的旧分类，避免下拉框让既有值失去回显。 */
const skillCategoryOptions = computed(() => buildSkillCategoryOptions([
  ...document.value.skills.map((item) => item.category),
  ...(profile.value?.skills ?? []).map((item) => item.category),
]))
const skillProficiencyOptions = [
  { value: 'BASIC', label: '基础（BASIC）' },
  { value: 'INTERMEDIATE', label: '熟练（INTERMEDIATE）' },
  { value: 'ADVANCED', label: '进阶（ADVANCED）' },
  { value: 'EXPERT', label: '专家（EXPERT）' },
]
type Choice = { value: string; label: string }
const selectedSource = ref<Record<ResumeSection, string | undefined>>({
  SUMMARY: undefined, EXPERIENCES: undefined, PROJECTS: undefined, SKILLS: undefined,
  EDUCATIONS: undefined, LANGUAGES: undefined,
})
const manualAddTestId: Record<ResumeSection, string> = {
  SUMMARY: '', EXPERIENCES: 'add-experience', PROJECTS: 'add-project',
  SKILLS: 'add-skill', EDUCATIONS: 'add-education', LANGUAGES: 'add-language',
}

/** 只列出尚未加入这份简历的档案事实；删除后仍能重新选入。 */
function availableChoices<T extends { id: string }>(
  facts: readonly T[] | undefined,
  included: readonly { source_fact_id: string | null }[],
  label: (fact: T) => string,
): Choice[] {
  const used = new Set(included.map((item) => item.source_fact_id))
  return (facts ?? []).filter((fact) => !used.has(fact.id)).map((fact) => ({ value: fact.id, label: label(fact) }))
}

const sourceChoices = computed<Record<ResumeSection, Choice[]>>(() => ({
  SUMMARY: [],
  EXPERIENCES: availableChoices(profile.value?.experiences, document.value.experiences, (item) => `${item.company} · ${item.title}`),
  PROJECTS: availableChoices(profile.value?.projects, document.value.projects, (item) => item.name),
  SKILLS: availableChoices(profile.value?.skills, document.value.skills, (item) => item.name),
  EDUCATIONS: availableChoices(profile.value?.educations, document.value.educations, (item) => item.school),
  LANGUAGES: availableChoices(profile.value?.languages, document.value.languages, (item) => item.language),
}))

/** 选择档案事实后复制已有字段并建立来源关联，不触碰已有简历条目。 */
function addSelectedFact(section: ResumeSection): void {
  if (section === 'SUMMARY') return
  const id = selectedSource.value[section]
  const source = profile.value
  if (!id || !source || !sourceChoices.value[section].some((option) => option.value === id)) return
  if (section === 'EXPERIENCES') {
    const fact = source.experiences.find((item) => item.id === id)
    if (fact) document.value.experiences.push(resumeExperienceFromProfile(fact))
  } else if (section === 'PROJECTS') {
    const fact = source.projects.find((item) => item.id === id)
    if (fact) document.value.projects.push(resumeProjectFromProfile(fact))
  } else if (section === 'SKILLS') {
    const fact = source.skills.find((item) => item.id === id)
    if (fact) document.value.skills.push(resumeSkillFromProfile(fact))
  } else if (section === 'EDUCATIONS') {
    const fact = source.educations.find((item) => item.id === id)
    if (fact) document.value.educations.push(resumeEducationFromProfile(fact))
  } else {
    const fact = source.languages.find((item) => item.id === id)
    if (fact) document.value.languages.push(resumeLanguageFromProfile(fact))
  }
  selectedSource.value[section] = undefined
}

/** 没有可复用事实时保留手动新增；手写条目没有伪造的档案来源。 */
function addManualFact(section: ResumeSection): void {
  if (section === 'EXPERIENCES') addExperience()
  else if (section === 'PROJECTS') addProject()
  else if (section === 'SKILLS') addSkill()
  else if (section === 'EDUCATIONS') addEducation()
  else if (section === 'LANGUAGES') addLanguage()
}

/** 把事实列表转成下拉选项，并补一项"手写（无来源）"。 */
function toOptions<TItem extends { id: string }>(
  items: readonly TItem[] | undefined,
  label: (item: TItem) => string,
): { value: string; label: string }[] {
  return [
    { value: '', label: '手写（无来源）' },
    ...(items ?? []).map((item) => ({ value: item.id, label: label(item) })),
  ]
}

/** 空串与纯空白一律写成 null：文档里只保留一种"未填写"，下游判定不必区分两种空。 */
function textOrNull(value: string): string | null {
  return value.trim() === '' ? null : value
}

/** 逗号分隔的标签文本 → 数组，与展示用的 `join(', ')` 对应。 */
function splitTags(text: string): string[] {
  return text
    .split(',')
    .map((tag) => tag.trim())
    .filter((tag) => tag !== '')
}

/** 写入条目的来源事实；空值表示改回"手写"。 */
function setSource(item: { source_fact_id: string | null }, value: unknown): void {
  item.source_fact_id = typeof value === 'string' && value !== '' ? value : null
}

/**
 * 写入联系方式；联系方式整体缺失时先建立空对象。
 *
 * 注意:
 *     模板里的输入绑定统一写成**内联箭头并标注参数类型**（`(value: string) => ...`）。
 *     两个原因：自动导入的组件其事件参数无法被推断，不标注就会报"隐式 any"；而把处理逻辑做成
 *     工厂函数再在模板里调用也不行——`@event="factory(item)"` 属于调用表达式，Vue 会把它包成
 *     `$event => factory(item)`，工厂返回的处理器会被丢弃，事件因此静默失效（实测如此）。
 */
function setContact(field: 'email' | 'phone', value: string): void {
  const contact = document.value.contact ?? { email: null, phone: null }
  contact[field] = textOrNull(value)
  document.value.contact = contact
}

/** 头像只保存在当前简历的联系方式中，不从档案或参考文件推断。 */
async function readPhoto(file: File): Promise<void> {
  photoError.value = null
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    photoError.value = '仅支持 PNG、JPEG 或 WebP 图片。'
    return
  }
  if (file.size > 256 * 1024) {
    photoError.value = '头像不能超过 256 KiB，请先压缩图片。'
    return
  }
  try {
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = () => reject(new Error('读取头像失败'))
      reader.readAsDataURL(file)
    })
    if (!loaded.value) return
    const contact = document.value.contact ?? { email: null, phone: null }
    contact.photo_data_url = dataUrl
    document.value.contact = contact
  } catch {
    photoError.value = '读取头像失败，请重新选择图片。'
  }
}

/** 阻止 Upload 自动发网络请求，由当前简历文档的自动保存流程统一持久化。 */
function beforeUploadPhoto(file: File): false {
  void readPhoto(file)
  return false
}

/** 删除当前简历头像；草稿由现有自动保存流程写入。 */
function removePhoto(): void {
  if (document.value.contact) document.value.contact.photo_data_url = null
  photoError.value = null
}

/** 写入简介正文；没有简介时先建立文本块。 */
function setSummaryText(text: string): void {
  document.value.summary = { text, source_fact_id: document.value.summary?.source_fact_id ?? null }
}

/**
 * 取某个条目上的字段级错误。
 *
 * 参数:
 *     section: 模块。
 *     index: 条目下标。
 *
 * 返回:
 *     string | null: 命中的原因；没有错误时返回 null。
 *
 * 说明:
 *     后端路径形如 `skills.0.source_fact_id`，因此按 `字段名.下标.` 前缀匹配。
 *     与具体字段名无关：同一个条目上的任何字段出错都应当标在这条上。
 */
function entryError(section: ResumeSection, index: number): string | null {
  const prefix = `${sectionDocumentKey(section)}.${index}.`
  const hit = Object.entries(fieldErrors.value).find(([path]) => path.startsWith(prefix))
  return hit?.[1] ?? null
}

/** 载入候选稿；同时读取档案，用于填充"来源事实"下拉。 */
async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    const loadedDraft = await fetchDraft(props.resumeId, props.draftId)
    draft.value = loadedDraft
    document.value = normalizeForEditing(loadedDraft.document_json)
    savedSnapshot.value = JSON.stringify(document.value)
    saveFailed.value = false
    loaded.value = true
  } catch (error: unknown) {
    loadError.value = parseServerError(error)
    loaded.value = false
  } finally {
    loading.value = false
  }

  try {
    profile.value = await fetchProfile()
  } catch {
    // 档案缺失只影响"来源事实"下拉的可选项，不影响编辑本身，因此不打断页面。
    profile.value = null
  }
}

/**
 * 编辑前的规范化。
 *
 * 注意:
 *     联系方式为 null 时补成空对象，使模板不必为"有没有联系方式"分支；
 *     规范化必须在取快照之前完成，否则刚打开页面就会被判定为"有未保存改动"。
 */
function normalizeForEditing(source: ResumeDocument): ResumeDocument {
  return { ...source, contact: source.contact ?? { email: null, phone: null } }
}

/** 保存整份文档。 */
async function save(): Promise<void> {
  if (draft.value === null || saving.value || !dirty.value) {
    return
  }

  // 发送固定快照；用户在请求期间继续输入时，响应不能把新输入覆盖掉。
  const submitted = JSON.stringify(document.value)
  saving.value = true
  saveFailed.value = false
  actionError.value = null
  fieldErrors.value = {}
  try {
    const updated = await updateDraft(props.resumeId, props.draftId, {
      version: draft.value.version,
      document: JSON.parse(submitted) as ResumeDocument,
    })
    draft.value = updated
    savedSnapshot.value = JSON.stringify(normalizeForEditing(updated.document_json))
    if (JSON.stringify(document.value) === submitted) document.value = normalizeForEditing(updated.document_json)
  } catch (error: unknown) {
    saveFailed.value = true
    const parsed = parseServerError(error)
    fieldErrors.value = parsed.fields
    // 字段级原因必须留在编辑器里（条目下方与顶部摘要）；没有字段信息的失败（网络、超时、
    // 服务端错误）改走全局通知，避免在编辑中的文档顶部插一块与当前内容无关的错误。
    if (isGlobalFailure(parsed)) {
      notifyFailure(parsed, '保存候选稿')
      actionError.value = null
    } else {
      actionError.value = parsed
    }
  } finally {
    saving.value = false
    if (!saveFailed.value && dirty.value) scheduleSave()
  }
}

/** 短暂停顿后保存，合并连续输入；新输入在保存中发生时由上一次请求完成后接续。 */
function scheduleSave(): void {
  if (saveTimer !== null) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveTimer = null
    void save()
  }, 700)
}

watch(() => JSON.stringify(document.value), () => {
  if (loaded.value && dirty.value) scheduleSave()
})

/** 路由切换先写入待保存改动；失败时留在编辑器，避免误以为内容已经落库。 */
onBeforeRouteLeave(async () => {
  if (saving.value) return false
  if (dirty.value) await save()
  return !dirty.value
})

/** 浏览器刷新/关闭无法等待异步写入，只能在仍有未保存内容时交由浏览器确认。 */
function warnBeforeUnload(event: BeforeUnloadEvent): void {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onBeforeUnmount(() => {
  if (saveTimer !== null) clearTimeout(saveTimer)
  window.removeEventListener('beforeunload', warnBeforeUnload)
})

/** 离开编辑器前先提交仍在等待防抖的改动；失败时留在页面供用户修复。 */
async function backToDetail(): Promise<void> {
  if (dirty.value) await save()
  if (!dirty.value && !saving.value) {
    await router.push({ name: 'resume-detail', params: { resumeId: props.resumeId } })
  }
}

/** 新增一条工作经历。 */
function addExperience(): void {
  const item: ResumeExperienceItem = {
    source_fact_id: null,
    company: '',
    title: '',
    location: null,
    start_date: null,
    end_date: null,
    highlights: [],
  }
  document.value.experiences.push(item)
}

/** 新增一个项目。 */
function addProject(): void {
  const item: ResumeProjectItem = {
    source_fact_id: null,
    name: '',
    role: null,
    description: null,
    tech_stack: [],
    url: null,
  }
  document.value.projects.push(item)
}

/** 新增一项技能。 */
function addSkill(): void {
  const item: ResumeSkillItem = { source_fact_id: null, name: '', category: null, proficiency: null }
  document.value.skills.push(item)
}

/** 新增一段教育经历。 */
function addEducation(): void {
  const item: ResumeEducationItem = {
    source_fact_id: null,
    school: '',
    major: null,
    degree: null,
    start_date: null,
    end_date: null,
  }
  document.value.educations.push(item)
}

/** 新增一项语言能力。 */
function addLanguage(): void {
  const item: ResumeLanguageItem = { source_fact_id: null, language: '', level: null }
  document.value.languages.push(item)
}

onMounted(() => {
  window.addEventListener('beforeunload', warnBeforeUnload)
  void load()
})
</script>

<template>
  <section class="resume-editor-view">
    <header class="page-header">
      <div>
        <h1>编辑简历</h1>
        <p class="subtitle">编辑不会影响已确认的版本；确认候选稿才会生成新版本。</p>
      </div>
      <a-space v-if="loaded">
        <span class="save-status" role="status" data-testid="save-status">{{ saveStatus }}</span>
        <a-button size="small" :disabled="saving" @click="backToDetail">返回</a-button>
        <a-button v-if="saveFailed" size="small" :loading="saving" data-testid="retry-save" @click="save">重试保存</a-button>
      </a-space>
    </header>

    <a-alert
      v-if="loadError"
      type="error"
      show-icon
      class="hint"
      :message="loadError.message"
      data-testid="load-error"
    />

    <a-alert
      v-if="actionError"
      type="error"
      show-icon
      closable
      class="hint"
      :message="actionError.message"
      data-testid="action-error"
      @close="actionError = null"
    >
      <template #description>
        <ul v-if="fieldErrorList.length > 0" class="field-errors">
          <li v-for="item in fieldErrorList" :key="item.path">{{ item.path }}：{{ item.reason }}</li>
        </ul>
      </template>
    </a-alert>

    <a-spin v-if="loading && !loaded" data-testid="loading" />

    <div v-if="loaded" class="resume-workspace">
      <div class="resume-form-pane" data-testid="resume-form-pane">
      <a-card size="small" title="头部信息" data-testid="panel-basics">
        <template #extra>
          <a-popover v-model:open="templateOpen" trigger="click" placement="rightTop" overlay-class-name="resume-template-popover">
            <template #content>
              <SectionSettingsPanel v-model="document" />
            </template>
            <a-button size="small" data-testid="template-management">模板管理</a-button>
          </a-popover>
        </template>
        <a-form layout="vertical">
          <a-form-item label="头像">
            <div class="photo-editor">
              <div class="photo-upload-box">
                <a-upload accept="image/png,image/jpeg,image/webp" list-type="picture-card" :show-upload-list="false" :before-upload="beforeUploadPhoto" data-testid="photo-upload">
                  <div class="photo-upload-content">
                    <img v-if="document.contact?.photo_data_url" :src="document.contact.photo_data_url" alt="当前头像，点击更换" class="photo-thumbnail" />
                    <template v-else><PlusOutlined /><span>上传头像</span></template>
                  </div>
                </a-upload>
              </div>
              <a-button v-if="document.contact?.photo_data_url" type="link" size="small" class="photo-remove" data-testid="photo-remove" @click="removePhoto">移除头像</a-button>
            </div>
            <p class="card-hint">PNG、JPEG 或 WebP，不超过 256 KiB；仅用于当前简历。</p>
            <p v-if="photoError" class="photo-error" role="alert" data-testid="photo-error">{{ photoError }}</p>
          </a-form-item>
          <div class="basics-fields">
          <a-form-item label="姓名">
            <a-input
              v-model:value="document.basics.full_name"
              :maxlength="100"
              data-testid="basics-full-name"
            />
          </a-form-item>
          <a-form-item label="城市">
            <a-input
              :value="document.basics.city ?? ''"
              :maxlength="100"
              @update:value="(value: string) => (document.basics.city = textOrNull(value))"
            />
          </a-form-item>
          <a-form-item label="一句话头衔" class="field-wide">
            <a-input
              :value="document.basics.headline ?? ''"
              :maxlength="200"
              data-testid="basics-headline"
              @update:value="(value: string) => (document.basics.headline = textOrNull(value))"
            />
          </a-form-item>
          <a-form-item label="邮箱">
            <a-input
              :value="document.contact?.email ?? ''"
              @update:value="(value: string) => setContact('email', value)"
            />
          </a-form-item>
          <a-form-item label="电话">
            <a-input
              :value="document.contact?.phone ?? ''"
              @update:value="(value: string) => setContact('phone', value)"
            />
          </a-form-item>
          <div class="field-wide">
            <p class="field-group-label">公开链接</p>
            <div v-for="(link, index) in document.basics.links" :key="index" class="link-row">
              <a-form-item label="链接名称"><a-input v-model:value="link.label" :maxlength="50" /></a-form-item>
              <a-form-item label="链接地址"><a-input v-model:value="link.url" :maxlength="2048" /></a-form-item>
              <a-button type="link" danger size="small" @click="document.basics.links.splice(index, 1)">
                删除
              </a-button>
            </div>
            <a-button size="small" @click="document.basics.links.push({ label: '', url: '' })">添加链接</a-button>
          </div>
          </div>
        </a-form>
      </a-card>

      <a-card
        v-for="section in document.section_order"
        :key="section"
        size="small"
        :title="SECTION_LABEL[section]"
        :data-testid="`panel-${section.toLowerCase()}`"
      >
        <template #extra>
          <span v-if="isSectionEmpty(document, section)" class="card-hint">暂无内容，不会出现在预览中</span>
        </template>

        <a-form layout="vertical">

        <template v-if="section === 'SUMMARY'">
          <div v-if="document.summary">
            <a-form-item label="个人简介">
              <a-textarea
                :value="document.summary?.text ?? ''"
                :rows="5"
                data-testid="summary-text"
                @update:value="setSummaryText"
              />
            </a-form-item>
            <a-button type="link" danger size="small" @click="document.summary = null">删除简介</a-button>
          </div>
          <a-button v-else size="small" @click="document.summary = { text: '', source_fact_id: null }">
            添加简介
          </a-button>
        </template>

        <template v-else-if="section === 'EXPERIENCES'">
          <div
            v-for="(item, index) in document.experiences"
            :key="index"
            class="entry"
            :data-testid="`entry-experiences-${index}`"
          >
            <div class="entry-fields">
              <a-form-item label="公司"><a-input v-model:value="item.company" :maxlength="200" /></a-form-item>
              <a-form-item label="职位"><a-input v-model:value="item.title" :maxlength="200" /></a-form-item>
              <a-form-item label="地点">
              <a-input
                :value="item.location ?? ''"
                :maxlength="100"
                @update:value="(value: string) => (item.location = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="开始时间">
              <a-input
                :value="item.start_date ?? ''"
                placeholder="YYYY-MM"
                @update:value="(value: string) => (item.start_date = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="结束时间">
              <a-input
                :value="item.end_date ?? ''"
                placeholder="留空表示至今"
                @update:value="(value: string) => (item.end_date = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="来源经历" extra="仅调整来源关联，不覆盖已编辑内容；填入档案内容请使用下方「从档案添加」。">
              <a-select
                :value="item.source_fact_id ?? ''"
                :options="experienceOptions"
                @change="(value: string) => setSource(item, value)"
              />
              </a-form-item>
              <a-button type="link" danger size="small" class="entry-delete" @click="document.experiences.splice(index, 1)">删除</a-button>
            </div>
            <a-form-item label="工作要点" class="entry-description">
              <a-textarea
              :value="item.highlights.join('\n')"
              :rows="5"
              placeholder="要点，每行一条"
              @update:value="(value: string) => (item.highlights = toLines(value))"
              />
            </a-form-item>
            <p v-if="entryError('EXPERIENCES', index)" class="entry-error" :data-testid="`field-error-experiences-${index}`">
              {{ entryError('EXPERIENCES', index) }}
            </p>
          </div>
        </template>

        <template v-else-if="section === 'PROJECTS'">
          <div
            v-for="(item, index) in document.projects"
            :key="index"
            class="entry"
            :data-testid="`entry-projects-${index}`"
          >
            <div class="entry-fields">
              <a-form-item label="项目名称"><a-input v-model:value="item.name" :maxlength="200" /></a-form-item>
              <a-form-item label="担任角色">
              <a-input
                :value="item.role ?? ''"
                :maxlength="100"
                @update:value="(value: string) => (item.role = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="技术栈">
              <a-input
                :value="item.tech_stack.join(', ')"
                placeholder="多个技术用逗号分隔"
                @update:value="(value: string) => (item.tech_stack = splitTags(value))"
              />
              </a-form-item>
              <a-form-item label="项目链接">
              <a-input
                :value="item.url ?? ''"
                :maxlength="2048"
                @update:value="(value: string) => (item.url = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="来源项目" extra="仅调整来源关联，不覆盖已编辑内容；填入档案内容请使用下方「从档案添加」。">
              <a-select
                :value="item.source_fact_id ?? ''"
                :options="projectOptions"
                @change="(value: string) => setSource(item, value)"
              />
              </a-form-item>
              <a-button type="link" danger size="small" class="entry-delete" @click="document.projects.splice(index, 1)">删除</a-button>
            </div>
            <a-form-item label="项目说明" class="entry-description">
              <a-textarea
              :value="item.description ?? ''"
              :rows="5"
              @update:value="(value: string) => (item.description = textOrNull(value))"
              />
            </a-form-item>
            <p v-if="entryError('PROJECTS', index)" class="entry-error" :data-testid="`field-error-projects-${index}`">
              {{ entryError('PROJECTS', index) }}
            </p>
          </div>
        </template>

        <template v-else-if="section === 'SKILLS'">
          <div v-for="(item, index) in document.skills" :key="index" class="entry" :data-testid="`entry-skills-${index}`">
            <div class="entry-fields">
              <a-form-item label="技能名称"><a-input v-model:value="item.name" :maxlength="100" :data-testid="`skill-${index}-name`" /></a-form-item>
              <a-form-item label="技能分类">
              <a-select
                :value="item.category ?? undefined"
                :options="skillCategoryOptions"
                :allow-clear="true"
                show-search
                placeholder="选择分类"
                :data-testid="`skill-${index}-category`"
                @change="(value: string | undefined) => (item.category = value ?? null)"
              />
              </a-form-item>
              <a-form-item label="展示分级">
              <a-auto-complete
                :value="item.proficiency ?? ''"
                :options="skillProficiencyOptions"
                placeholder="选择常用分级或输入自定义文本"
                :maxlength="32"
                @update:value="(value: string) => (item.proficiency = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="来源技能" extra="仅调整来源关联，不覆盖已编辑内容；填入档案内容请使用下方「从档案添加」。">
              <a-select
                :value="item.source_fact_id ?? ''"
                :options="skillOptions"
                @change="(value: string) => setSource(item, value)"
              />
              </a-form-item>
              <a-button type="link" danger size="small" class="entry-delete" @click="document.skills.splice(index, 1)">删除</a-button>
            </div>
            <p v-if="entryError('SKILLS', index)" class="entry-error" :data-testid="`field-error-skills-${index}`">
              {{ entryError('SKILLS', index) }}
            </p>
          </div>
        </template>

        <template v-else-if="section === 'EDUCATIONS'">
          <div
            v-for="(item, index) in document.educations"
            :key="index"
            class="entry"
            :data-testid="`entry-educations-${index}`"
          >
            <div class="entry-fields">
              <a-form-item label="学校"><a-input v-model:value="item.school" :maxlength="200" /></a-form-item>
              <a-form-item label="专业">
              <a-input
                :value="item.major ?? ''"
                :maxlength="200"
                @update:value="(value: string) => (item.major = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="学历">
              <DegreeField
                :value="item.degree ?? ''"
                :max-length="64"
                @update-value="(value: string) => (item.degree = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="开始时间">
              <a-input
                :value="item.start_date ?? ''"
                placeholder="YYYY-MM-DD"
                @update:value="(value: string) => (item.start_date = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="结束时间">
              <a-input
                :value="item.end_date ?? ''"
                placeholder="YYYY-MM-DD"
                @update:value="(value: string) => (item.end_date = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="来源教育经历" extra="仅调整来源关联，不覆盖已编辑内容；填入档案内容请使用下方「从档案添加」。">
              <a-select
                :value="item.source_fact_id ?? ''"
                :options="educationOptions"
                @change="(value: string) => setSource(item, value)"
              />
              </a-form-item>
              <a-button type="link" danger size="small" class="entry-delete" @click="document.educations.splice(index, 1)">删除</a-button>
            </div>
            <p
              v-if="entryError('EDUCATIONS', index)"
              class="entry-error"
              :data-testid="`field-error-educations-${index}`"
            >
              {{ entryError('EDUCATIONS', index) }}
            </p>
          </div>
        </template>

        <template v-else>
          <div
            v-for="(item, index) in document.languages"
            :key="index"
            class="entry"
            :data-testid="`entry-languages-${index}`"
          >
            <div class="entry-fields">
              <a-form-item label="语言"><a-input v-model:value="item.language" :maxlength="64" /></a-form-item>
              <a-form-item label="水平">
              <a-input
                :value="item.level ?? ''"
                placeholder="例如 CET-6"
                :maxlength="64"
                @update:value="(value: string) => (item.level = textOrNull(value))"
              />
              </a-form-item>
              <a-form-item label="来源语言能力" extra="仅调整来源关联，不覆盖已编辑内容；填入档案内容请使用下方「从档案添加」。">
              <a-select
                :value="item.source_fact_id ?? ''"
                :options="languageOptions"
                @change="(value: string) => setSource(item, value)"
              />
              </a-form-item>
              <a-button type="link" danger size="small" class="entry-delete" @click="document.languages.splice(index, 1)">删除</a-button>
            </div>
            <p v-if="entryError('LANGUAGES', index)" class="entry-error" :data-testid="`field-error-languages-${index}`">
              {{ entryError('LANGUAGES', index) }}
            </p>
          </div>
        </template>
        <div v-if="section !== 'SUMMARY'" class="fact-add-controls">
          <a-select
            :value="selectedSource[section]"
            :options="sourceChoices[section]"
            :disabled="sourceChoices[section].length === 0"
            show-search
            option-filter-prop="label"
            :placeholder="sourceChoices[section].length ? `选择档案中的${SECTION_LABEL[section]}` : `档案中暂无可添加的${SECTION_LABEL[section]}`"
            :aria-label="`从档案选择${SECTION_LABEL[section]}`"
            :data-testid="`source-picker-${section}`"
            @change="(value: string) => (selectedSource[section] = value)"
          />
          <a-button type="primary" size="small" :disabled="!selectedSource[section]" :data-testid="`add-selected-${section}`" @click="addSelectedFact(section)">从档案添加</a-button>
          <a-button type="link" size="small" :data-testid="manualAddTestId[section]" @click="addManualFact(section)">手动新增</a-button>
        </div>
        </a-form>
      </a-card>
      </div>
      <aside class="resume-preview-pane" data-testid="resume-preview-pane">
        <ResumePreview :document="document" />
      </aside>
    </div>
  </section>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  max-width: none;
}

.page-header h1 {
  font-size: 1.25rem;
  margin: 0 0 0.25rem;
}

.subtitle,
.card-hint {
  color: #6b7280;
  font-size: 0.85rem;
  margin: 0;
}

.hint {
  max-width: 70rem;
  margin: 1rem 0;
}

.field-errors {
  margin: 0;
  padding-left: 1.1em;
}

.link-row {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.link-row > :first-child { flex: 0 0 30%; }
.link-row > :nth-child(2) { flex: 1 1 auto; }
.link-row > * { min-width: 0; }
.link-row :deep(.ant-form-item) { margin-bottom: 0; }
.field-group-label { margin: 0 0 0.5rem; color: #4e5969; font-weight: 550; }

.basics-fields, .entry-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 16px; }
.basics-fields { row-gap: 0; }
.basics-fields > * { min-width: 0; }
.basics-fields .field-wide { grid-column: 1 / -1; }
.entry-fields { align-items: start; gap: 18px 16px; }
.entry-fields > * { min-width: 0; max-width: 100%; }
.entry-fields > :not(.entry-delete) { width: 100%; }
.entry-fields :deep(.ant-form-item) { margin-bottom: 0; }
.basics-fields :deep(.ant-form-item-label), .entry-fields :deep(.ant-form-item-label), .link-row :deep(.ant-form-item-label) { padding-bottom: 6px; }
.basics-fields :deep(.ant-input), .entry-fields :deep(.ant-input), .link-row :deep(.ant-input) { min-height: 40px; border-radius: var(--ja-radius); }
.entry-fields :deep(.ant-select-selector) { min-height: 40px; border-radius: var(--ja-radius); align-items: center; }
.entry-delete { justify-self: end; }
.entry-description { margin-top: 16px; }
.fact-add-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.fact-add-controls :deep(.ant-select) { flex: 1 1 210px; min-width: 180px; }

.entry {
  padding: 1rem 0 1.25rem;
  border-bottom: 1px solid var(--ja-color-border);
}

.entry:first-of-type { padding-top: 0; }
.entry:last-of-type {
  margin-bottom: 1rem;
}

.entry-error {
  margin: 0.35rem 0 0;
  color: #cf1322;
  font-size: 0.85rem;
}
.photo-editor { display: grid; grid-template-columns: 104px max-content; align-items: center; justify-content: start; gap: 0.75rem; }
.photo-upload-box { width: 104px; height: 104px; min-width: 0; }
.photo-upload-box :deep(.ant-upload-wrapper) { display: block; width: 104px; height: 104px; }
.photo-editor :deep(.ant-upload-select-picture-card) { width: 104px; height: 104px; margin: 0; padding: 0; overflow: hidden; }
.photo-remove { opacity: 0; pointer-events: none; transition: opacity 0.15s ease; }
.photo-editor:hover .photo-remove, .photo-editor:focus-within .photo-remove { opacity: 1; pointer-events: auto; }
@media (hover: none) { .photo-remove { opacity: 1; pointer-events: auto; } }
.photo-upload-content { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.5rem; width: 100%; height: 100%; }
.photo-thumbnail { width: 100%; height: 100%; object-fit: cover; }
.photo-error { margin: 0.25rem 0 0; color: #cf1322; font-size: 0.85rem; }
.save-status { color: var(--ja-color-muted); font-size: 0.85rem; }
.resume-workspace { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 24px; align-items: start; }
.resume-form-pane { min-width: 0; display: grid; gap: 24px; }
.resume-form-pane :deep(.ant-card-head-title) { color: #111827; font-size: 16px; font-weight: 700; }
.resume-preview-pane { min-width: 0; overflow: auto; background: var(--ja-color-canvas); padding: 0; position: sticky; top: 0; max-height: 100vh; }
.resume-preview-pane :deep(.a4-page) { max-width: 100%; }
@media (max-width: 1100px) { .resume-workspace { grid-template-columns: minmax(0, 1fr); } .resume-preview-pane { position: static; max-height: none; } }
@media (max-width: 600px) { .basics-fields, .entry-fields { grid-template-columns: minmax(0, 1fr); } }
</style>
