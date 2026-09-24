/** @vitest-environment jsdom */
/** 简历导入必须经过文件选择、外部发送同意和人工确认三个阶段。 */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { confirmProfileImport, previewProfileImport, type ProfileImportPreview } from '@/shared/api/profile'

import ProfileImportPanel from './ProfileImportPanel.vue'

vi.mock('@/shared/api/profile', () => ({
  previewProfileImport: vi.fn(),
  confirmProfileImport: vi.fn(),
}))

const candidate: ProfileImportPreview = {
  filename: 'sample.html',
  source_hash: 'a'.repeat(64),
  candidate: {
    full_name: '张三', name_quote: '张三', headline: null, email: null, phone: null, city: null,
    skills: [{ name: 'Python', source_quote: '熟悉 Python' }],
    experiences: [], educations: [],
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(previewProfileImport).mockResolvedValue(candidate)
  vi.mocked(confirmProfileImport).mockResolvedValue({
    profile_id: 'id', created_profile: true, skills_added: 1, experiences_added: 0, educations_added: 0,
  })
})

enableAutoUnmount(afterEach)

it('未经外部发送同意不能预览，未经核对不能确认写入', async () => {
  // 用 `attrs` 传入的监听器断言事件，而不是 `wrapper.emitted()`：
  // VTU 在 `defineEmits` 声明的自定义事件上不会记录到 `emitted()`，
  // 直接断言会得到"事件从未触发"的假结论（实测如此）。
  const onChanged = vi.fn()
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false }, attrs: { onChanged } })
  const input = wrapper.find('input[type="file"]')
  const document = new File(['<html><body>张三 熟悉 Python</body></html>'], 'sample.html', { type: 'text/html' })
  Object.defineProperty(input.element, 'files', { configurable: true, value: [document] })
  await input.trigger('change')
  expect(wrapper.text()).toContain('sample.html')

  expect(wrapper.find('[data-testid="preview-import"]').attributes('disabled')).toBeDefined()
  expect(previewProfileImport).not.toHaveBeenCalled()

  await wrapper.find('[data-testid="profile-import-consent"]').setValue(true)
  expect(wrapper.find('[data-testid="preview-import"]').attributes('disabled')).toBeUndefined()
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await new Promise(resolve => setTimeout(resolve, 30))
  await flushPromises()
  expect(wrapper.find('[data-testid="profile-import-error"]').exists()).toBe(false)
  expect(previewProfileImport).toHaveBeenCalledOnce()
  expect(wrapper.text()).toContain('姓名原文：张三')
  expect(wrapper.find('[data-testid="confirm-import"]').attributes('disabled')).toBeDefined()
  expect(confirmProfileImport).not.toHaveBeenCalled()

  await wrapper.find('[data-testid="profile-import-reviewed"]').setValue(true)
  await wrapper.find('[data-testid="confirm-import"]').trigger('click')
  await flushPromises()
  expect(confirmProfileImport).toHaveBeenCalledOnce()
  expect(onChanged).toHaveBeenCalledTimes(1)
})
