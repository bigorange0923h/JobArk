/**
 * 简历文档的纯逻辑。
 *
 * 这里只放"可以脱离界面单独验证"的规则，界面组件只负责把结果渲染出来：
 *
 * - **顺序**：`section_order` 始终是六个模块的完整排列。界面不提供增删模块，只做相邻交换，
 *   因此任何一步移动的结果仍然是原集合的一个排列——不会丢项，也不会产生重复。
 * - **显隐**：`hidden_sections` 只表达用户的**显式**隐藏。空模块不渲染，但不会被写进这个列表：
 *   "暂时没有内容"与"用户选择隐藏"必须可区分，否则用户重新填了内容仍然看不到那个模块，
 *   而界面上找不到是谁关掉了它。
 * - **溯源**：从档案生成文档时逐条写入 `source_fact_id`。溯源在生成的时刻就建立，
 *   而不是等用户事后补——补录的引用最容易变成"看着像有依据"。
 */

import type { Profile } from '@/shared/api/profile'
import type {
  ResumeDocument,
  ResumeEducationItem,
  ResumeExperienceItem,
  ResumeLanguageItem,
  ResumeProjectItem,
  ResumeSection,
  ResumeSkillItem,
} from '@/shared/api/resume'

/** 默认模块顺序，代表一份常规简历的排版次序。必须与后端 `DEFAULT_SECTION_ORDER` 一致。 */
export const SECTION_ORDER_DEFAULT: readonly ResumeSection[] = [
  'SUMMARY',
  'EXPERIENCES',
  'PROJECTS',
  'SKILLS',
  'EDUCATIONS',
  'LANGUAGES',
]

/** 模块在界面上的名称；与后端枚举分开维护，因为后者是存储取值。 */
export const SECTION_LABEL: Record<ResumeSection, string> = {
  SUMMARY: '个人简介',
  EXPERIENCES: '工作经历',
  PROJECTS: '项目经历',
  SKILLS: '技能',
  EDUCATIONS: '教育经历',
  LANGUAGES: '语言能力',
}

/**
 * 列表类模块与文档字段的对应关系。
 *
 * `SUMMARY` 不在其中：它是单个文本块而不是条目列表，空判定与渲染方式都不同，
 * 单独分支比把它硬塞进这张表更清楚。
 */
const LIST_KEY_BY_SECTION = {
  EXPERIENCES: 'experiences',
  PROJECTS: 'projects',
  SKILLS: 'skills',
  EDUCATIONS: 'educations',
  LANGUAGES: 'languages',
} as const satisfies Record<Exclude<ResumeSection, 'SUMMARY'>, keyof ResumeDocument>

/**
 * 构造一份空白文档。
 *
 * 注意:
 *    姓名是后端必填字段，空白文档**不能直接提交**。界面应从档案生成文档
 *    （`createDocumentFromProfile`，天然带有姓名），只在档案尚未建立时以空白文档起步并提示用户填写。
 */
export function createBlankDocument(): ResumeDocument {
  return {
    schema_version: 1,
    basics: { full_name: '', headline: null, city: null, links: [] },
    contact: null,
    summary: null,
    experiences: [],
    projects: [],
    skills: [],
    educations: [],
    languages: [],
    section_order: [...SECTION_ORDER_DEFAULT],
    hidden_sections: [],
  }
}

/**
 * 判断模块是否没有可渲染的内容。
 *
 * 参数:
 *     document: 简历文档。
 *     section: 模块。
 *
 * 返回:
 *     boolean: 没有内容返回 true。
 *
 * 注意:
 *     简介的判空要按去除空白后的结果判断：只敲了几个空格的简介渲染出来是一片空白，
 *     与"没填"在版面上没有区别，但会被当成有内容而输出标题。
 */
export function isSectionEmpty(document: ResumeDocument, section: ResumeSection): boolean {
  if (section === 'SUMMARY') {
    return document.summary === null || document.summary.text.trim() === ''
  }
  return document[LIST_KEY_BY_SECTION[section]].length === 0
}

/**
 * 取模块在文档中的字段名。
 *
 * 参数:
 *     section: 模块。
 *
 * 返回:
 *     string: 该模块在 `ResumeDocument` 上的字段名，例如 `SKILLS` → `skills`。
 *
 * 说明:
 *     后端校验失败时给出的字段路径形如 `skills.0.source_fact_id`，界面要把这类错误定位到
 *     具体条目就必须知道模块与字段名的对应关系。这条对应关系只在这里定义一处。
 */
export function sectionDocumentKey(section: ResumeSection): string {
  return section === 'SUMMARY' ? 'summary' : LIST_KEY_BY_SECTION[section]
}

/**
 * 把多行文本拆成条目要点。
 *
 * 参数:
 *     text: 用户输入的多行文本。
 *
 * 返回:
 *     string[]: 去除空行与首尾空白后的要点，与 `createDocumentFromProfile` 使用同一套规则。
 */
export function toLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
}

/**
 * 计算实际参与渲染的模块。
 *
 * 参数:
 *     document: 简历文档。
 *
 * 返回:
 *     ResumeSection[]: 顺序遵循 `section_order`，并排除被显式隐藏的模块与空模块。
 *
 * 注意:
 *     这是**只读**计算：它不会把跳过的空模块写进 `hidden_sections`。
 *     编辑器与 A4 预览都从这里取模块列表，两处才不会出现"预览少了一块"的不一致。
 */
export function renderedSections(document: ResumeDocument): ResumeSection[] {
  return document.section_order.filter(
    (section) => !document.hidden_sections.includes(section) && !isSectionEmpty(document, section),
  )
}

/**
 * 把模块上移或下移一位。
 *
 * 参数:
 *     order: 当前顺序。
 *     section: 要移动的模块。
 *     direction: 移动方向。
 *
 * 返回:
 *     ResumeSection[]: 新顺序；已在边界时返回与入参等值的新数组。
 *
 * 注意:
 *     只做相邻交换：与"先删除再插入"相比，交换不可能因为边界判断失误而丢项。
 */
export function moveSection(
  order: readonly ResumeSection[],
  section: ResumeSection,
  direction: 'up' | 'down',
): ResumeSection[] {
  const moved = [...order]
  const from = moved.indexOf(section)
  if (from === -1) {
    return moved
  }

  const to = direction === 'up' ? from - 1 : from + 1
  const current = moved[from]
  const neighbour = moved[to]
  if (to < 0 || to >= moved.length || current === undefined || neighbour === undefined) {
    return moved
  }

  moved[from] = neighbour
  moved[to] = current
  return moved
}

/**
 * 设置模块的显隐。
 *
 * 参数:
 *     hidden: 当前隐藏列表。
 *     section: 模块。
 *     hiddenNow: 目标是隐藏还是显示。
 *
 * 返回:
 *     ResumeSection[]: 新的隐藏列表；重复设置同一状态不会产生重复项。
 */
export function setSectionHidden(
  hidden: readonly ResumeSection[],
  section: ResumeSection,
  hiddenNow: boolean,
): ResumeSection[] {
  if (!hiddenNow) {
    return hidden.filter((item) => item !== section)
  }
  return hidden.includes(section) ? [...hidden] : [...hidden, section]
}

/**
 * 用档案中的事实生成一份简历文档。
 *
 * 参数:
 *     profile: 当前档案。
 *
 * 返回:
 *     ResumeDocument: 每个条目都带有指向来源事实的主键。
 *
 * 说明:
 *     这是"新建候选稿"的默认起点：姓名、联系方式与简介来自档案，五类事实各生成一个条目。
 *     生成结果只是初稿，用户可以删改条目；但**删改后仍保留的条目**带着可核验的来源，
 *     而手写新增的条目没有来源——后端只在条目引用了修订中不存在的事实时才拒绝保存。
 */
export function createDocumentFromProfile(profile: Profile): ResumeDocument {
  const summary = profile.summary?.trim()

  return {
    ...createBlankDocument(),
    basics: {
      full_name: profile.full_name,
      headline: profile.headline,
      city: profile.city,
      links: profile.links.map((link) => ({ label: link.label, url: link.url })),
    },
    contact: { email: profile.email, phone: profile.phone },
    // 简介的依据是档案本身：档案主键也出现在修订快照里，因此这是后端认可的合法溯源。
    summary: summary === undefined || summary === '' ? null : { text: summary, source_fact_id: profile.id },
    experiences: profile.experiences.map(
      (item): ResumeExperienceItem => ({
        source_fact_id: item.id,
        company: item.company,
        title: item.title,
        location: item.location,
        start_date: item.start_date,
        end_date: item.end_date,
        highlights: toHighlights(item.responsibilities, item.achievements),
      }),
    ),
    projects: profile.projects.map(
      (item): ResumeProjectItem => ({
        source_fact_id: item.id,
        name: item.name,
        role: item.role,
        description: item.description,
        tech_stack: [...item.tech_stack],
        url: item.url,
      }),
    ),
    skills: profile.skills.map(
      (item): ResumeSkillItem => ({
        source_fact_id: item.id,
        name: item.name,
        category: item.category,
        proficiency: item.proficiency,
      }),
    ),
    educations: profile.educations.map(
      (item): ResumeEducationItem => ({
        source_fact_id: item.id,
        school: item.school,
        major: item.major,
        degree: item.degree,
        start_date: item.start_date,
        end_date: item.end_date,
      }),
    ),
    // 档案里的语言备注（note）在简历文档中没有对应字段：简历上只列语言与水平，
    // 备注属于"补充说明"，放进简历会让版式不可控。不为了不丢字段而给它硬造位置。
    languages: profile.languages.map(
      (item): ResumeLanguageItem => ({
        source_fact_id: item.id,
        language: item.language,
        level: item.level,
      }),
    ),
  }
}

/**
 * 把档案的职责与成果文本拆成简历要点。
 *
 * 参数:
 *     responsibilities: 职责描述；可空。
 *     achievements: 成果描述；可空。
 *
 * 返回:
 *     string[]: 逐行拆分的要点，已去除空行与首尾空白。
 *
 * 说明:
 *     档案里这两个字段是整段文本，而简历上按行展示。空行必须丢弃：它们会在 A4 上变成
 *     无法解释的空白，而用户看不到"空行"这个实体，也就无从删除。
 */
function toHighlights(responsibilities: string | null, achievements: string | null): string[] {
  return [responsibilities, achievements].flatMap((text) => (text === null ? [] : toLines(text)))
}
