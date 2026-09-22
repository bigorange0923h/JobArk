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

import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

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
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

import SectionSettingsPanel from './components/SectionSettingsPanel.vue'
import { SECTION_LABEL, createBlankDocument, isSectionEmpty, sectionDocumentKey, toLines } from './document'

const props = defineProps<{ resumeId: string; draftId: string }>()

const router = useRouter()

/** 正在编辑的文档；始终是有效对象，使模板不必到处判空。 */
const document = ref<ResumeDocument>(createBlankDocument())
const draft = ref<ResumeDraft | null>(null)
const profile = ref<Profile | null>(null)
const loaded = ref(false)
const loading = ref(false)
const saving = ref(false)
const loadError = ref<ParsedServerError | null>(null)
const actionError = ref<ParsedServerError | null>(null)
const fieldErrors = ref<Record<string, string>>({})
/** 最近一次与服务端一致的文档快照；用于判断"有没有改动"，避免无意义的往返与版本自增。 */
const savedSnapshot = ref('')

const dirty = computed(() => JSON.stringify(document.value) !== savedSnapshot.value)

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
  if (draft.value === null) {
    return
  }

  saving.value = true
  actionError.value = null
  fieldErrors.value = {}
  try {
    const updated = await updateDraft(props.resumeId, props.draftId, {
      version: draft.value.version,
      document: document.value,
    })
    draft.value = updated
    document.value = normalizeForEditing(updated.document_json)
    savedSnapshot.value = JSON.stringify(document.value)
  } catch (error: unknown) {
    const parsed = parseServerError(error)
    actionError.value = parsed
    fieldErrors.value = parsed.fields
  } finally {
    saving.value = false
  }
}

/** 返回详情页。 */
function backToDetail(): void {
  void router.push({ name: 'resume-detail', params: { resumeId: props.resumeId } })
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
  void load()
})
</script>

<template>
  <section class="resume-editor-view">
    <header class="page-header">
      <div>
        <h1>编辑候选稿</h1>
        <p class="subtitle">编辑不会影响已确认的版本；确认候选稿才会生成新版本。</p>
      </div>
      <a-space v-if="loaded">
        <a-button size="small" :loading="loading" data-testid="reload" @click="load">重新加载</a-button>
        <a-button size="small" @click="backToDetail">返回</a-button>
        <a-button
          type="primary"
          size="small"
          :disabled="!dirty"
          :loading="saving"
          data-testid="save-draft"
          @click="save"
        >
          保存
        </a-button>
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

    <template v-if="loaded">
      <a-card size="small" title="头部信息" data-testid="panel-basics">
        <a-form layout="vertical">
          <a-form-item label="姓名">
            <a-input
              v-model:value="document.basics.full_name"
              :maxlength="100"
              data-testid="basics-full-name"
            />
          </a-form-item>
          <a-form-item label="一句话头衔">
            <a-input
              :value="document.basics.headline ?? ''"
              :maxlength="200"
              data-testid="basics-headline"
              @update:value="(value: string) => (document.basics.headline = textOrNull(value))"
            />
          </a-form-item>
          <a-form-item label="城市">
            <a-input
              :value="document.basics.city ?? ''"
              :maxlength="100"
              @update:value="(value: string) => (document.basics.city = textOrNull(value))"
            />
          </a-form-item>
          <a-form-item label="联系方式">
            <a-space direction="vertical" style="width: 100%">
              <a-input
                :value="document.contact?.email ?? ''"
                placeholder="邮箱"
                @update:value="(value: string) => setContact('email', value)"
              />
              <a-input
                :value="document.contact?.phone ?? ''"
                placeholder="电话"
                @update:value="(value: string) => setContact('phone', value)"
              />
            </a-space>
          </a-form-item>
          <a-form-item label="公开链接">
            <div v-for="(link, index) in document.basics.links" :key="index" class="link-row">
              <a-input v-model:value="link.label" placeholder="名称" :maxlength="50" />
              <a-input v-model:value="link.url" placeholder="地址" :maxlength="2048" />
              <a-button type="link" danger size="small" @click="document.basics.links.splice(index, 1)">
                删除
              </a-button>
            </div>
            <a-button size="small" @click="document.basics.links.push({ label: '', url: '' })">添加链接</a-button>
          </a-form-item>
        </a-form>
      </a-card>

      <SectionSettingsPanel v-model="document" />

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

        <template v-if="section === 'SUMMARY'">
          <div v-if="document.summary">
            <a-textarea
              :value="document.summary?.text ?? ''"
              :rows="3"
              data-testid="summary-text"
              @update:value="setSummaryText"
            />
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
            <a-space wrap>
              <a-input v-model:value="item.company" placeholder="公司" :maxlength="200" />
              <a-input v-model:value="item.title" placeholder="职位" :maxlength="200" />
              <a-input
                :value="item.location ?? ''"
                placeholder="地点"
                :maxlength="100"
                @update:value="(value: string) => (item.location = textOrNull(value))"
              />
              <a-input
                :value="item.start_date ?? ''"
                placeholder="开始 YYYY-MM-DD"
                @update:value="(value: string) => (item.start_date = textOrNull(value))"
              />
              <a-input
                :value="item.end_date ?? ''"
                placeholder="结束（空表示至今）"
                @update:value="(value: string) => (item.end_date = textOrNull(value))"
              />
              <a-select
                :value="item.source_fact_id ?? ''"
                :options="experienceOptions"
                style="min-width: 12rem"
                @change="(value: string) => setSource(item, value)"
              />
              <a-button type="link" danger size="small" @click="document.experiences.splice(index, 1)">删除</a-button>
            </a-space>
            <a-textarea
              :value="item.highlights.join('\n')"
              :rows="3"
              placeholder="要点，每行一条"
              @update:value="(value: string) => (item.highlights = toLines(value))"
            />
            <p v-if="entryError('EXPERIENCES', index)" class="entry-error" :data-testid="`field-error-experiences-${index}`">
              {{ entryError('EXPERIENCES', index) }}
            </p>
          </div>
          <a-button size="small" data-testid="add-experience" @click="addExperience">添加工作经历</a-button>
        </template>

        <template v-else-if="section === 'PROJECTS'">
          <div
            v-for="(item, index) in document.projects"
            :key="index"
            class="entry"
            :data-testid="`entry-projects-${index}`"
          >
            <a-space wrap>
              <a-input v-model:value="item.name" placeholder="项目名" :maxlength="200" />
              <a-input
                :value="item.role ?? ''"
                placeholder="角色"
                :maxlength="100"
                @update:value="(value: string) => (item.role = textOrNull(value))"
              />
              <a-input
                :value="item.tech_stack.join(', ')"
                placeholder="技术栈，逗号分隔"
                @update:value="(value: string) => (item.tech_stack = splitTags(value))"
              />
              <a-input
                :value="item.url ?? ''"
                placeholder="链接"
                :maxlength="2048"
                @update:value="(value: string) => (item.url = textOrNull(value))"
              />
              <a-select
                :value="item.source_fact_id ?? ''"
                :options="projectOptions"
                style="min-width: 12rem"
                @change="(value: string) => setSource(item, value)"
              />
              <a-button type="link" danger size="small" @click="document.projects.splice(index, 1)">删除</a-button>
            </a-space>
            <a-textarea
              :value="item.description ?? ''"
              :rows="2"
              placeholder="项目说明"
              @update:value="(value: string) => (item.description = textOrNull(value))"
            />
            <p v-if="entryError('PROJECTS', index)" class="entry-error" :data-testid="`field-error-projects-${index}`">
              {{ entryError('PROJECTS', index) }}
            </p>
          </div>
          <a-button size="small" data-testid="add-project" @click="addProject">添加项目</a-button>
        </template>

        <template v-else-if="section === 'SKILLS'">
          <div v-for="(item, index) in document.skills" :key="index" class="entry" :data-testid="`entry-skills-${index}`">
            <a-space wrap>
              <a-input v-model:value="item.name" placeholder="技能名" :maxlength="100" :data-testid="`skill-${index}-name`" />
              <a-input
                :value="item.category ?? ''"
                placeholder="分类"
                :maxlength="64"
                @update:value="(value: string) => (item.category = textOrNull(value))"
              />
              <a-input
                :value="item.proficiency ?? ''"
                placeholder="展示用分级，例如 ADVANCED"
                :maxlength="32"
                @update:value="(value: string) => (item.proficiency = textOrNull(value))"
              />
              <a-select
                :value="item.source_fact_id ?? ''"
                :options="skillOptions"
                style="min-width: 12rem"
                @change="(value: string) => setSource(item, value)"
              />
              <a-button type="link" danger size="small" @click="document.skills.splice(index, 1)">删除</a-button>
            </a-space>
            <p v-if="entryError('SKILLS', index)" class="entry-error" :data-testid="`field-error-skills-${index}`">
              {{ entryError('SKILLS', index) }}
            </p>
          </div>
          <a-button size="small" data-testid="add-skill" @click="addSkill">添加技能</a-button>
        </template>

        <template v-else-if="section === 'EDUCATIONS'">
          <div
            v-for="(item, index) in document.educations"
            :key="index"
            class="entry"
            :data-testid="`entry-educations-${index}`"
          >
            <a-space wrap>
              <a-input v-model:value="item.school" placeholder="学校" :maxlength="200" />
              <a-input
                :value="item.major ?? ''"
                placeholder="专业"
                :maxlength="200"
                @update:value="(value: string) => (item.major = textOrNull(value))"
              />
              <a-input
                :value="item.degree ?? ''"
                placeholder="学历"
                :maxlength="64"
                @update:value="(value: string) => (item.degree = textOrNull(value))"
              />
              <a-input
                :value="item.start_date ?? ''"
                placeholder="开始 YYYY-MM-DD"
                @update:value="(value: string) => (item.start_date = textOrNull(value))"
              />
              <a-input
                :value="item.end_date ?? ''"
                placeholder="结束 YYYY-MM-DD"
                @update:value="(value: string) => (item.end_date = textOrNull(value))"
              />
              <a-select
                :value="item.source_fact_id ?? ''"
                :options="educationOptions"
                style="min-width: 12rem"
                @change="(value: string) => setSource(item, value)"
              />
              <a-button type="link" danger size="small" @click="document.educations.splice(index, 1)">删除</a-button>
            </a-space>
            <p
              v-if="entryError('EDUCATIONS', index)"
              class="entry-error"
              :data-testid="`field-error-educations-${index}`"
            >
              {{ entryError('EDUCATIONS', index) }}
            </p>
          </div>
          <a-button size="small" data-testid="add-education" @click="addEducation">添加教育经历</a-button>
        </template>

        <template v-else>
          <div
            v-for="(item, index) in document.languages"
            :key="index"
            class="entry"
            :data-testid="`entry-languages-${index}`"
          >
            <a-space wrap>
              <a-input v-model:value="item.language" placeholder="语言" :maxlength="64" />
              <a-input
                :value="item.level ?? ''"
                placeholder="水平，例如 CET-6"
                :maxlength="64"
                @update:value="(value: string) => (item.level = textOrNull(value))"
              />
              <a-select
                :value="item.source_fact_id ?? ''"
                :options="languageOptions"
                style="min-width: 12rem"
                @change="(value: string) => setSource(item, value)"
              />
              <a-button type="link" danger size="small" @click="document.languages.splice(index, 1)">删除</a-button>
            </a-space>
            <p v-if="entryError('LANGUAGES', index)" class="entry-error" :data-testid="`field-error-languages-${index}`">
              {{ entryError('LANGUAGES', index) }}
            </p>
          </div>
          <a-button size="small" data-testid="add-language" @click="addLanguage">添加语言能力</a-button>
        </template>
      </a-card>
    </template>
  </section>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  max-width: 70rem;
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
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}

.entry {
  padding: 0.6rem 0;
  border-bottom: 1px solid #f3f4f6;
}

.entry:last-of-type {
  border-bottom: none;
}

.entry-error {
  margin: 0.35rem 0 0;
  color: #cf1322;
  font-size: 0.85rem;
}
</style>
