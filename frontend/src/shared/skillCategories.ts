/** 与服务端常用分类保持一致；历史分类可在调用处并入选项，不能静默丢弃。 */
export const SKILL_CATEGORIES = [
  '编程语言', '前端开发', '后端开发', 'AI 应用', '数据库', '中间件', '开发工具', '其他',
] as const

/** 构造下拉选项时保留既有分类，即使它不在常用列表内。 */
export function skillCategoryOptions(values: readonly (string | null | undefined)[]): { value: string; label: string }[] {
  const categories = new Set<string>(SKILL_CATEGORIES)
  for (const value of values) if (value?.trim()) categories.add(value)
  return [...categories].map((category) => ({ value: category, label: category }))
}
