<script setup lang="ts">
/** 核心事实字段区：手填与导入共用字段、控件、排版和来源说明位置。 */
import { computed, nextTick, ref } from 'vue'
import { skillCategoryOptions as buildSkillCategoryOptions } from '@/shared/skillCategories'
import { PROFILE_FACT_SECTIONS, projectDescription, type ProfileFactField, type ProfileFactKey, type ProfileFactSection } from '../profileFormFields'
import DegreeField from './DegreeField.vue'

type FactItem = Record<string, unknown>
const props = withDefaults(defineProps<{
  items: Record<ProfileFactKey, FactItem[]>
  mode: 'manual' | 'import'
  sourceTitles?: Record<string, string>
  statuses?: Record<string, string>
  errors?: Record<string, string>
  /** 「所属工作经历」下拉的选项；只在档案页传入（导入候选还没有可关联的 id）。 */
  experienceOptions?: { value: string; label: string; disabled?: boolean }[]
}>(), { sourceTitles: () => ({}), statuses: () => ({}), errors: () => ({}), experienceOptions: () => [] })
const emit = defineEmits<{
  updateField: [key: ProfileFactKey, index: number, field: ProfileFactField, value: unknown]
  fieldBlur: [key: ProfileFactKey, index: number]
  addItem: [key: ProfileFactKey]
  removeItem: [key: ProfileFactKey, index: number]
}>()

function valueOf(key: ProfileFactKey, item: FactItem, field: ProfileFactField): string {
  if (key === 'projects' && field.name === 'description') return projectDescription(item)
  const value = item[field.name]
  return typeof value === 'string' ? value : ''
}

/**
 * 当前模式下要渲染的字段。
 *
 * 「所属工作经历」只在档案页出现：导入候选里的工作经历还没有 id，没有任何东西可关联；
 * 这里直接不渲染而不是禁用——它在候选阶段根本不是一个可做的选择。
 */
function fieldsOf(section: ProfileFactSection, mode: 'manual' | 'import'): readonly ProfileFactField[] {
  return mode === 'manual' ? section.fields : section.fields.filter((field) => field.kind !== 'experience')
}

function tagsOf(item: FactItem, field: ProfileFactField): string[] {
  const value = item[field.name]
  return Array.isArray(value) ? value as string[] : []
}

function quoteOf(item: FactItem): string {
  if (item['origin'] === 'MANUAL') {
    const oldQuote = item['original_source_quote']
    return typeof oldQuote === 'string' && oldQuote !== '' ? `本人填写；原摘录（不再作为来源）：${oldQuote}` : '本人填写'
  }
  const quote = item['source_quote']
  return typeof quote === 'string' && quote !== '' ? `本条来自简历原文：${quote}` : '本人填写'
}

const editingSkill = ref<number | null>(null)
const skillSection = PROFILE_FACT_SECTIONS.find((section) => section.key === 'skills')
const skillNameField = skillSection?.fields.find((field) => field.name === 'name')
const skillCategoryField = skillSection?.fields.find((field) => field.name === 'category')
const skillCategoryOptions = computed(() => buildSkillCategoryOptions(props.items.skills.map((item) =>
  typeof item['category'] === 'string' ? item['category'] : null,
)))

/** 已保存技能只有关联证据 ID；展示证据标题，不臆测为某段简历原文。 */
function skillSource(item: FactItem, mode: 'manual' | 'import', sourceTitles: Record<string, string>): string {
  if (mode === 'import') return `来源：${quoteOf(item)}`
  const evidenceId = item['source_evidence_id']
  const title = typeof evidenceId === 'string' ? sourceTitles[evidenceId] : undefined
  return title ? `来源：${title}` : '来源：本人填写'
}

/** 名称默认以文本按钮呈现；点击后立即聚焦同一位置的输入框。 */
async function startSkillEdit(index: number, event: MouseEvent): Promise<void> {
  const card = (event.currentTarget as HTMLElement).closest('.skill-card')
  editingSkill.value = index
  await nextTick()
  card?.querySelector('input')?.focus()
}

function finishSkillEdit(index: number): void {
  if (editingSkill.value !== index) return
  editingSkill.value = null
  emit('fieldBlur', 'skills', index)
}

function updateSkill(index: number, value: unknown): void {
  if (skillNameField) emit('updateField', 'skills', index, skillNameField, value)
}

/** 分类是建议而非原文事实；日常编辑立即保存，导入核对只修改候选草稿。 */
function updateSkillCategory(index: number, value: unknown): void {
  if (!skillCategoryField) return
  emit('updateField', 'skills', index, skillCategoryField, value)
  if (props.mode === 'manual') emit('fieldBlur', 'skills', index)
}

function removeSkill(index: number): void {
  editingSkill.value = null
  emit('removeItem', 'skills', index)
}

function statusKey(key: ProfileFactKey, index: number): string {
  return `${key}-${index}`
}
</script>

<template>
  <section v-for="section in PROFILE_FACT_SECTIONS" :key="section.key" class="fact-section" :data-testid="`form-section-${section.key}`">
    <h3>{{ section.title }}</h3>
    <a-empty v-if="items[section.key].length === 0" :description="`暂无${section.title}，可在下方新增`" />
    <div v-if="section.key === 'skills' && items.skills.length > 0" class="skill-grid" data-testid="skill-grid">
      <div v-for="(item, index) in items.skills" :key="String(item['id'] ?? index)" class="skill-card" :data-testid="`form-item-skills-${index}`">
        <div class="skill-content">
          <a-input
            v-if="editingSkill === index"
            :value="valueOf('skills', item, skillNameField!)"
            class="skill-name-input"
            :data-testid="`fact-skills-${index}-name-input`"
            @update:value="(value: unknown) => updateSkill(index, value)"
            @blur="finishSkillEdit(index)"
            @keydown.enter.prevent="finishSkillEdit(index)"
          />
          <button v-else type="button" class="skill-name" :data-testid="`fact-skills-${index}-name`" :aria-label="`编辑技能 ${valueOf('skills', item, skillNameField!) || '未填写'}`" @click="startSkillEdit(index, $event)">
            {{ valueOf('skills', item, skillNameField!) || '点击填写技能名称' }}
          </button>
          <a-form layout="vertical" class="skill-category-form"><a-form-item :label="mode === 'import' ? '建议分类（可调整）' : '技能分类'" class="skill-category-field">
            <a-select
              :value="typeof item['category'] === 'string' && item['category'] !== '' ? item['category'] : undefined"
              :options="skillCategoryOptions"
              allow-clear
              show-search
              option-filter-prop="label"
              placeholder="未分类"
              :data-testid="`fact-skills-${index}-category`"
              @change="(value: unknown) => updateSkillCategory(index, value)"
            />
          </a-form-item></a-form>
          <p class="skill-source" :title="skillSource(item, mode, sourceTitles)">{{ skillSource(item, mode, sourceTitles) }}<span v-if="mode === 'manual' && statuses[statusKey('skills', index)]"> · {{ statuses[statusKey('skills', index)] }}</span><span v-if="errors[`skills-${index}-name`]"> · {{ errors[`skills-${index}-name`] }}</span></p>
        </div>
        <a-popconfirm v-if="mode === 'manual' && item['id']" title="确认归档这项技能？历史引用会保留，可在归档列表恢复。" ok-text="归档" cancel-text="取消" @confirm="removeSkill(index)">
          <a-button type="text" danger size="small" :data-testid="`remove-item-skills-${index}`" :aria-label="`删除技能 ${valueOf('skills', item, skillNameField!)}`">归档</a-button>
        </a-popconfirm>
        <a-button v-else type="text" danger size="small" :data-testid="`remove-item-skills-${index}`" :aria-label="`删除技能 ${valueOf('skills', item, skillNameField!)}`" @click="removeSkill(index)">删除</a-button>
      </div>
    </div>
    <a-card v-for="(item, index) in section.key === 'skills' ? [] : items[section.key]" :key="String(item['id'] ?? index)" size="small" class="fact-item" :data-testid="`form-item-${section.key}-${index}`">
      <template #title>{{ section.title }} {{ index + 1 }}</template>
      <template #extra>
        <a-popconfirm v-if="mode === 'manual' && item['id']" :title="`确认归档这条${section.title}？历史引用会保留。`" ok-text="归档" cancel-text="取消" @confirm="emit('removeItem', section.key, index)">
          <a-button type="link" danger size="small">归档</a-button>
        </a-popconfirm>
        <a-button v-else type="link" danger size="small" :data-testid="`remove-item-${section.key}-${index}`" @click="emit('removeItem', section.key, index)">移除</a-button>
      </template>
      <a-form layout="vertical" class="profile-field-grid">
        <a-form-item v-for="field in fieldsOf(section, mode)" :key="field.name" :label="field.label" :required="field.required" :class="{ 'profile-field-grid__wide': field.wide }" :help="errors[`${section.key}-${index}-${field.name}`]" :validate-status="errors[`${section.key}-${index}-${field.name}`] ? 'error' : undefined">
          <a-input v-if="field.kind === 'text'" :value="valueOf(section.key, item, field)" allow-clear :data-testid="`fact-${section.key}-${index}-${field.name}`" @update:value="(value: unknown) => emit('updateField', section.key, index, field, value)" @blur="emit('fieldBlur', section.key, index)" />
          <a-textarea v-else-if="field.kind === 'textarea'" :value="valueOf(section.key, item, field)" :rows="5" allow-clear :data-testid="`fact-${section.key}-${index}-${field.name}`" @update:value="(value: unknown) => emit('updateField', section.key, index, field, value)" @blur="emit('fieldBlur', section.key, index)" />
          <a-date-picker v-else-if="field.kind === 'date'" :value="valueOf(section.key, item, field) || null" value-format="YYYY-MM-DD" class="full-width" allow-clear :data-testid="`fact-${section.key}-${index}-${field.name}`" @update:value="(value: unknown) => emit('updateField', section.key, index, field, value)" @change="emit('fieldBlur', section.key, index)" />
          <a-date-picker v-else-if="field.kind === 'month'" :value="valueOf(section.key, item, field) || null" picker="month" format="YYYY-MM" value-format="YYYY-MM-DD" class="full-width" allow-clear :data-testid="`fact-${section.key}-${index}-${field.name}`" @update:value="(value: unknown) => emit('updateField', section.key, index, field, value)" @change="emit('fieldBlur', section.key, index)" />
          <DegreeField v-else-if="field.kind === 'degree'" :value="valueOf(section.key, item, field)" :testid="`fact-${section.key}-${index}-${field.name}`" @update-value="(value: string) => emit('updateField', section.key, index, field, value)" @blur="emit('fieldBlur', section.key, index)" />
          <a-select v-else-if="field.kind === 'experience'" :value="valueOf(section.key, item, field) || undefined" :options="experienceOptions" allow-clear show-search option-filter-prop="label" placeholder="不关联（个人项目）" :data-testid="`fact-${section.key}-${index}-${field.name}`" @update:value="(value: unknown) => emit('updateField', section.key, index, field, value)" @change="emit('fieldBlur', section.key, index)" />
          <a-select v-else :value="tagsOf(item, field)" mode="tags" :token-separators="[',']" :data-testid="`fact-${section.key}-${index}-${field.name}`" @update:value="(value: unknown) => emit('updateField', section.key, index, field, value)" @blur="emit('fieldBlur', section.key, index)" />
        </a-form-item>
      </a-form>
      <p v-if="mode === 'import'" class="source-quote">{{ quoteOf(item) }}</p>
      <p v-if="statuses[statusKey(section.key, index)]" class="save-status" role="status">{{ statuses[statusKey(section.key, index)] }}</p>
    </a-card>
    <a-button type="dashed" block :data-testid="`add-item-${section.key}`" @click="emit('addItem', section.key)">新增{{ section.title }}</a-button>
  </section>
</template>

<style scoped>
.fact-section { margin-top: 20px; }
.fact-section h3 { font-size: 15px; margin-bottom: 10px; }
.fact-item { margin-bottom: 10px; }
.fact-item :deep(.ant-form-item) { margin-bottom: 8px; }
.skill-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
.skill-card { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 8px; min-width: 0; padding: 12px; border: 1px solid var(--ja-color-border); border-radius: var(--ja-radius); background: var(--ja-color-surface); }
.skill-content { min-width: 0; }
.skill-category-field { margin: 8px 0 0; }
.skill-category-field :deep(.ant-form-item-label) { padding-bottom: 4px; }
.skill-category-field :deep(.ant-select) { width: 100%; }
.skill-name { display: block; width: 100%; padding: 2px 0; border: 0; background: transparent; color: var(--ja-color-text); font: inherit; font-weight: 600; text-align: left; overflow-wrap: anywhere; cursor: text; }
.skill-name:focus-visible { outline: 2px solid var(--ja-color-primary); outline-offset: 2px; border-radius: 2px; }
.skill-source { margin: 5px 0 0; color: var(--ja-color-muted); font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.skill-name-input { width: 100%; }
@media (max-width: 640px) { .skill-grid { grid-template-columns: minmax(0, 1fr); } }
.full-width { width: 100%; }
.source-quote, .save-status { margin: 8px 0 0; font-size: 12px; line-height: 1.6; color: var(--ja-color-muted); overflow-wrap: anywhere; }
</style>
