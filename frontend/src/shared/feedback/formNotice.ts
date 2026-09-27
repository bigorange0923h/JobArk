/** 表单通知：保留字段级错误，同时用 Alert 色系的轻量通知提醒。 */
import { notification } from 'ant-design-vue'

export type FormNoticeKind = 'success' | 'info' | 'warning' | 'error'

export interface FormNoticeOptions {
  kind: FormNoticeKind
  title: string
  detail?: string
  /** 同一表单的重复提示用固定键替换，避免用户反复点击时堆叠。 */
  key: string
}

/** 滚动并聚焦具体字段；只定位，不替用户修改或提交表单。 */
export function focusFormTarget(target: HTMLElement | null): void {
  if (!target) return
  target.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  const focusable = target.matches('input, textarea, select, button, [tabindex]')
    ? target
    : target.querySelector<HTMLElement>('input, textarea, select, button, [tabindex]')
  focusable?.focus()
}

/** 通知不是唯一错误载体；调用方仍须保留字段错误，并在首次校验失败时自动定位。 */
export function notifyFormIssue(options: FormNoticeOptions): void {
  notification[options.kind]({
    key: options.key,
    message: options.title,
    description: options.detail,
    class: `ja-form-notice ja-form-notice--${options.kind}`,
    placement: 'topRight',
    duration: 5,
  })
}
