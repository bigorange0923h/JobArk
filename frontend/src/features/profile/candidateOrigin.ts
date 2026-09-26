/**
 * 导入候选条目的来源判断：这条内容还能不能算「来自简历原文」。
 *
 * 规则与后端 `import_service` 一一对应（见 docs/requirements/v1.md 2.1）：
 * - 文字字段（含技术栈每一项）的取值必须落在摘录内；
 * - 日期字段只要求年份出现在摘录里（简历常只写年份或年月）。
 *
 * 为什么前端也要判断：用户在候选页改动的那一刻，界面上就该显示来源已变成「本人填写」，
 * 而不是等到确认时被后端拒绝或疏漏。真正的把关仍在后端：客户端说什么是不可信的。
 */

import type { ItemOrigin } from '@/shared/api/profile'

/** 与后端 `_normalize` 等价的空白折叠，用于摘录比对。 */
export function normalizeForQuote(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

/** 条目的来源；缺省按「来自简历原文」处理，与后端默认语义一致。 */
export function originOf(item: Record<string, unknown>): ItemOrigin {
  return item['origin'] === 'MANUAL' ? 'MANUAL' : 'RESUME'
}

/** 条目当前的摘录；`MANUAL` 条目在契约上不带摘录，因此返回空字符串。 */
export function quoteOf(item: Record<string, unknown>): string {
  const value = item['source_quote']
  return typeof value === 'string' ? value : ''
}

/**
 * 内容是否已偏离摘录。
 *
 * 参数:
 *   values: 必须落在摘录内的取值（文字、多行文本与技术栈的每一项）。
 *   years: 必须出现在摘录里的年份（日期字段的年份）。
 *   quote: 条目的原文摘录。
 *
 * 返回:
 *   boolean: true 表示该条目不能再按「简历原文」记录来源。
 */
export function deviatesFromQuote(
  values: readonly string[],
  years: readonly string[],
  quote: string,
): boolean {
  const normalizedQuote = normalizeForQuote(quote)
  if (normalizedQuote === '') return true
  if (
    values.some(
      (value) => value.trim() !== '' && !normalizedQuote.includes(normalizeForQuote(value)),
    )
  ) {
    return true
  }
  return years.some((year) => year !== '' && !quote.includes(year))
}
