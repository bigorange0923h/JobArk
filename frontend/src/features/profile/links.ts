/**
 * 公开链接的共享规则。
 *
 * “创建个人档案”表单与导入候选表单共用同一套判断，不各自维护一份：
 * 两边对“整行留空要不要提交”“只填一半算不算错”的看法必须一致，否则同一份输入在两条路径上
 * 会得到不同结果（一条静默丢弃、另一条被后端以 422 拒绝）。
 */

import type { ProfileLink } from '@/shared/api/profile'

/** 整行留空视为“用户只是点开了输入框”，不参与提交。 */
export function meaningfulLinks(links: readonly ProfileLink[]): ProfileLink[] {
  return links.filter((link) => link.label.trim() !== '' || link.url.trim() !== '')
}

/**
 * 只填了一半的链接行。
 *
 * 这种情况用户意图不明，必须由用户补全或删掉：提交上去只会得到一条难懂的嵌套字段错误。
 */
export function incompleteLinks(links: readonly ProfileLink[]): ProfileLink[] {
  return meaningfulLinks(links).filter((link) => link.label.trim() === '' || link.url.trim() === '')
}

/** 提交给后端的形态：丢掉整行留空的行，并去掉首尾空白。 */
export function submittableLinks(links: readonly ProfileLink[]): ProfileLink[] {
  return meaningfulLinks(links).map((link) => ({ label: link.label.trim(), url: link.url.trim() }))
}
