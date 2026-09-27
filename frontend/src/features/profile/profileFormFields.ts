/** 核心档案表单的四类事实字段；手填与导入只在保存策略上分叉。 */
export type ProfileFactKey = 'skills' | 'experiences' | 'projects' | 'educations'
export type ProfileFactFieldKind = 'text' | 'textarea' | 'date' | 'degree' | 'tags'

export interface ProfileFactField {
  name: string
  label: string
  kind: ProfileFactFieldKind
  required?: boolean
  wide?: boolean
}

export interface ProfileFactSection {
  key: ProfileFactKey
  title: string
  fields: readonly ProfileFactField[]
}

/** 字段名称与导入候选、日常档案接口对齐，来源元数据不混进可编辑的事实字段。 */
export const PROFILE_FACT_SECTIONS: readonly ProfileFactSection[] = [
  {
    key: 'skills', title: '技能',
    fields: [{ name: 'name', label: '技能名称', kind: 'text', required: true }],
  },
  {
    key: 'experiences', title: '工作经历',
    fields: [
      { name: 'company', label: '公司', kind: 'text', required: true },
      { name: 'title', label: '职位', kind: 'text', required: true },
      { name: 'location', label: '地点', kind: 'text' },
      { name: 'start_date', label: '开始日期', kind: 'date', required: true },
      { name: 'end_date', label: '结束日期', kind: 'date' },
      { name: 'responsibilities', label: '职责', kind: 'textarea', wide: true },
      { name: 'achievements', label: '成果', kind: 'textarea', wide: true },
    ],
  },
  {
    key: 'projects', title: '项目经历',
    fields: [
      { name: 'name', label: '项目名称', kind: 'text', required: true },
      { name: 'role', label: '本人角色', kind: 'text' },
      { name: 'description', label: '项目说明', kind: 'textarea', wide: true },
      { name: 'tech_stack', label: '技术栈', kind: 'tags' },
      { name: 'url', label: '项目链接', kind: 'text' },
      { name: 'start_date', label: '开始日期', kind: 'date' },
      { name: 'end_date', label: '结束日期', kind: 'date' },
    ],
  },
  {
    key: 'educations', title: '教育经历',
    fields: [
      { name: 'school', label: '学校', kind: 'text', required: true },
      { name: 'major', label: '专业', kind: 'text' },
      { name: 'degree', label: '学历/学位', kind: 'degree' },
      { name: 'start_date', label: '开始日期', kind: 'date' },
      { name: 'end_date', label: '结束日期', kind: 'date' },
    ],
  },
]

/** 项目导入候选有拆分字段，正式档案只有说明；编辑时展示最终会写入的完整说明。 */
export function projectDescription(item: Record<string, unknown>): string {
  const parts = [item['description'], item['responsibilities'], item['achievements']]
  return parts.filter((part): part is string => typeof part === 'string' && part.trim() !== '').join('\n')
}
