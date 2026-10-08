/** 核心档案表单的四类事实字段；手填与导入只在保存策略上分叉。 */
export type ProfileFactKey = 'skills' | 'experiences' | 'projects' | 'educations'
/**
 * `month`：只选到月的日期。
 *
 * 工作经历的时间不需要精确到日，因此用月份选择器；写入接口的值仍是完整日期，
 * 日固定为 1——与既有约定（原文只写年月时，缺失的月/日以 1 补位）保持一致，
 * 后端与数据库无需改动。
 */
export type ProfileFactFieldKind = 'text' | 'textarea' | 'date' | 'month' | 'degree' | 'experience' | 'tags' | 'select'

export interface ProfileFactField {
  name: string
  label: string
  kind: ProfileFactFieldKind
  required?: boolean
  wide?: boolean
  options?: { value: string; label: string }[]
}

export interface ProfileFactSection {
  key: ProfileFactKey
  title: string
  fields: readonly ProfileFactField[]
}

/** 字段名称与导入候选、日常档案接口对齐，来源元数据不混进可编辑的事实字段。 */
export const PROFILE_FACT_SECTIONS: readonly ProfileFactSection[] = [
  {
    key: 'experiences', title: '工作经历',
    fields: [
      { name: 'company', label: '公司', kind: 'text', required: true },
      { name: 'title', label: '职位', kind: 'text', required: true },
      // 不再让用户填写工作地点：这条信息对匹配与简历生成没有用，徒增填写负担。
      // 数据库列与接口字段保留——导入时模型抽取到的地点有原文摘录支撑，会照原样写入，
      // 历史值也不会因为字段从表单消失而被清掉（界面只是不再编辑它）。
      // 工作经历的时间只到月：多数简历也只写到月，要求填到日只会逼用户随手编一个日子。
      { name: 'start_date', label: '开始时间', kind: 'month', required: true },
      { name: 'end_date', label: '结束时间', kind: 'month' },
      { name: 'responsibilities', label: '职责', kind: 'textarea', wide: true },
      { name: 'achievements', label: '成果', kind: 'textarea', wide: true },
    ],
  },
  {
    key: 'projects', title: '项目经历',
    fields: [
      { name: 'name', label: '项目名称', kind: 'text', required: true },
      { name: 'role', label: '本人角色', kind: 'text' },
      // 关联到某段工作经历；留空即个人项目。只在档案页渲染：导入候选的工作经历还没有 id。
      { name: 'experience_id', label: '所属工作经历', kind: 'experience' },
      { name: 'description', label: '项目说明', kind: 'textarea', wide: true },
      { name: 'achievements', label: '成果', kind: 'textarea', wide: true },
      { name: 'tech_stack', label: '技术栈', kind: 'tags' },
      { name: 'url', label: '项目链接', kind: 'text' },
      // 与工作经历一致：项目时间也只到月。
      { name: 'start_date', label: '开始时间', kind: 'month' },
      { name: 'end_date', label: '结束时间', kind: 'month' },
    ],
  },
  {
    key: 'skills', title: '技能',
    fields: [
      { name: 'name', label: '技能名称', kind: 'text', required: true },
      { name: 'category', label: '技能分类', kind: 'text' },
    ],
  },
  {
    key: 'educations', title: '教育经历',
    fields: [
      { name: 'school', label: '学校', kind: 'text', required: true },
      { name: 'major', label: '专业', kind: 'text' },
      { name: 'degree', label: '学历/学位原文', kind: 'degree' },
      { name: 'degree_level', label: '确认学历层次（可留空）', kind: 'select', options: [
        { value: 'HIGH_SCHOOL', label: '高中/中专' }, { value: 'ASSOCIATE', label: '大专' },
        { value: 'BACHELOR', label: '本科' }, { value: 'MASTER', label: '硕士' },
        { value: 'DOCTOR', label: '博士' }, { value: 'OTHER', label: '其他' },
      ] },
      { name: 'study_mode', label: '确认学习形式（可留空）', kind: 'select', options: [
        { value: 'FULL_TIME', label: '全日制' }, { value: 'PART_TIME', label: '非全日制' }, { value: 'OTHER', label: '其他' },
      ] },
      { name: 'start_date', label: '开始日期', kind: 'date' },
      { name: 'end_date', label: '结束日期', kind: 'date' },
    ],
  },
]

/** 项目导入候选把职责拆成独立字段，正式档案并入说明；编辑时展示最终会写入的说明文本。 */
export function projectDescription(item: Record<string, unknown>): string {
  const parts = [item['description'], item['responsibilities']]
  return parts.filter((part): part is string => typeof part === 'string' && part.trim() !== '').join('\n')
}
