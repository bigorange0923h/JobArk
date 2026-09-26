/**
 * 档案基本信息字段的单一来源。
 *
 * 创建/编辑档案页与导入候选核对页必须显示同一套字段（顺序、标签、长度上限、帮助文本），
 * 否则两边会各自演化出“创建时叫城市、核对时叫所在地”这类漂移。字段顺序也在这里固定：
 * 页面只按本数组渲染，不各自重排。
 *
 * 边界：这里只声明**标量文本字段**。公开链接是唯一的数组字段，由 `ProfileBasicsPanel.vue`
 * 单独渲染；导入候选（后端 `ImportCandidate`）也不包含个人简介与公开链接，因此候选页只取
 * 本文件给出的子集，而不是另写一份字段表。
 */

/** 基本信息字段的控件类型。 */
export type BasicFieldKind = 'text' | 'textarea'

/** 基本信息字段名，与后端请求体字段名一致。 */
export type BasicFieldName = 'full_name' | 'headline' | 'summary' | 'email' | 'phone' | 'city'

/** 一个基本信息字段。 */
export interface BasicField {
  /** 字段名；同时是表单绑定名与提交请求体的键。 */
  name: BasicFieldName
  label: string
  kind: BasicFieldKind
  /** 创建档案时是否必填；领域校验仍由后端最终裁决。 */
  required?: boolean
  /** 长度上限，与后端 schema 对齐；未标注表示后端未设上限。 */
  maxLength?: number
  placeholder?: string
  help?: string
  /** 长文本字段独占一行，避免与普通字段挤在同一行。 */
  wide?: boolean
}

/** 创建档案与候选核对共用的字段定义（顺序即渲染顺序）。 */
export const BASIC_FIELDS: readonly BasicField[] = [
  { name: 'full_name', label: '姓名', kind: 'text', required: true, maxLength: 100, help: '用于简历与投递材料，请填真实姓名。' },
  { name: 'headline', label: '一句话头衔', kind: 'text', maxLength: 200, placeholder: '例如：后端工程师' },
  { name: 'summary', label: '个人简介', kind: 'textarea', wide: true, placeholder: '概述你的经验方向，供简历与匹配参考' },
  { name: 'email', label: '邮箱', kind: 'text', maxLength: 320 },
  { name: 'phone', label: '手机', kind: 'text', maxLength: 50 },
  { name: 'city', label: '所在城市', kind: 'text', maxLength: 100 },
]

/**
 * 导入候选实际支持的字段名。
 *
 * 后端 `ImportCandidate` 只携带姓名、头衔、邮箱、手机与城市：简历导入不产出个人简介，
 * 公开链接也不在候选契约内。候选页缺少这些字段是契约事实，不是界面遗漏。
 */
export type ImportBasicFieldName = 'full_name' | 'headline' | 'email' | 'phone' | 'city'

/** 候选支持的基本信息字段；`name` 收窄后可直接索引 `ImportCandidate`。 */
export interface ImportBasicField extends BasicField {
  name: ImportBasicFieldName
}

const IMPORT_CANDIDATE_FIELD_NAMES: readonly ImportBasicFieldName[] = [
  'full_name',
  'headline',
  'email',
  'phone',
  'city',
]

/**
 * 候选核对页使用的基本信息字段；顺序与创建档案页完全一致。
 *
 * 用类型谓词过滤而不是再抄一份字段表：一旦共享定义改了标签或帮助文本，候选页自动同步。
 */
export const IMPORT_BASIC_FIELDS: readonly ImportBasicField[] = BASIC_FIELDS.filter(
  (field): field is ImportBasicField =>
    (IMPORT_CANDIDATE_FIELD_NAMES as readonly string[]).includes(field.name),
)
