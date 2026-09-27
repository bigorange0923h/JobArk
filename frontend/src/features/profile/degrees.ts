/**
 * 学历/学位取值的单一来源。
 *
 * 档案页的教育经历表单与导入候选的教育经历共用它：两处各列一份选项，迟早会出现
 * "这边有硕士、那边没有"这类漂移。
 *
 * 为什么要有"其他"：后端 `degree` 是**自由字符串**而不是枚举，历史数据与模型抽取里都存在
 * 列表外的写法（"学士""研究生""MBA"）。选择器必须能原样回显并保存它们，否则用户只是编辑学校
 * 就会把学历改没——这与城市选择器保留海外／旧称值是同一条原则。
 */

/** 一个学历选项。 */
export interface DegreeOption {
  value: string
  label: string
}

/**
 * 常见学历层次，顺序由低到高。
 *
 * `value` 即写入档案的字符串，用"本科""硕士"这类最常见写法，避免与既有数据（如 `本科`）
 * 对不上；学位差异（学士／硕士／博士）放进 label 里提示，不改变写入值。
 *
 * 「本科（非全日制）」是单独一项而不是自动推断：学习形式（全日制／非全日制）属于本人陈述，
 * 系统不得从学校或年份猜——猜错等于替用户编造履历。默认的「本科」即全日制。
 */
export const DEGREE_OPTIONS: readonly DegreeOption[] = [
  { value: '高中', label: '高中' },
  { value: '中专', label: '中专' },
  { value: '大专', label: '大专' },
  { value: '本科', label: '本科（学士）' },
  { value: '本科（非全日制）', label: '本科（非全日制）' },
  { value: '硕士', label: '硕士' },
  { value: '博士', label: '博士' },
]

/** 值是否在预设选项内；列表外的值一律走手动填写，不改写、不丢弃。 */
export function isKnownDegree(value: string): boolean {
  return DEGREE_OPTIONS.some((option) => option.value === value.trim())
}
