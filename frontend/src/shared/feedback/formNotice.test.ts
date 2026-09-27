/** @vitest-environment jsdom */
import { expect, it, vi } from 'vitest'
import { notification } from 'ant-design-vue'
import { focusFormTarget, notifyFormIssue } from './formNotice'

it('表单通知带语义色类名且不提供二次定位按钮', () => {
  const warning = vi.spyOn(notification, 'warning').mockImplementation(() => undefined)
  try {
    notifyFormIssue({ kind: 'warning', title: '请补齐必填项', detail: '技能名称不能为空', key: 'test-form' })
    expect(warning).toHaveBeenCalledOnce()
    const args = warning.mock.calls[0]?.[0]
    expect(args).toMatchObject({ class: 'ja-form-notice ja-form-notice--warning', placement: 'topRight', duration: 5 })
    expect(args?.btn).toBeUndefined()
  } finally {
    warning.mockRestore()
  }
})

it('首次校验失败时可自动滚动并聚焦字段', () => {
  const field = document.createElement('input')
  const scroll = vi.fn()
  field.scrollIntoView = scroll
  document.body.appendChild(field)
  try {
    focusFormTarget(field)
    expect(scroll).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' })
    expect(document.activeElement).toBe(field)
  } finally {
    field.remove()
  }
})

it('目标不存在时定位安全退出', () => {
  expect(() => focusFormTarget(null)).not.toThrow()
})
