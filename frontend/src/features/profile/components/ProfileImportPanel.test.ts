/** @vitest-environment jsdom */
/** 简历导入必须经过文件选择、外部发送同意和人工确认三个阶段。 */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { confirmProfileImport, previewProfileImportStream, type ProfileImportPreview } from '@/shared/api/profile'

import ProfileImportPanel from './ProfileImportPanel.vue'

vi.mock('@/shared/api/profile', () => ({
  previewProfileImportStream: vi.fn(),
  confirmProfileImport: vi.fn(),
}))

const candidate: ProfileImportPreview = {
  filename: 'sample.html',
  source_hash: 'a'.repeat(64),
  candidate: {
    full_name: '张三', name_quote: '张三', headline: null, email: null, phone: null, city: null,
    skills: [{ name: 'Python', source_quote: '熟悉 Python' }],
    experiences: [], projects: [], educations: [],
  },
  completeness: { status: 'COMPLETE', valid_item_count: 1, rejected_item_count: 0, unmapped_field_count: 0 },
  rejected_items: [],
  warnings: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(previewProfileImportStream).mockResolvedValue(candidate)
  vi.mocked(confirmProfileImport).mockResolvedValue({
    profile_id: 'id', created_profile: true, skills_added: 1, experiences_added: 0, projects_added: 0, educations_added: 0,
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
  expect(previewProfileImportStream).not.toHaveBeenCalled()

  await wrapper.find('[data-testid="profile-import-consent"]').setValue(true)
  expect(wrapper.find('[data-testid="preview-import"]').attributes('disabled')).toBeUndefined()
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await new Promise(resolve => setTimeout(resolve, 30))
  await flushPromises()
  expect(wrapper.find('[data-testid="profile-import-error"]').exists()).toBe(false)
  expect(previewProfileImportStream).toHaveBeenCalledOnce()
  expect(wrapper.text()).toContain('姓名原文：张三')
  expect(wrapper.find('[data-testid="confirm-import"]').attributes('disabled')).toBeDefined()
  expect(confirmProfileImport).not.toHaveBeenCalled()

  await wrapper.find('[data-testid="profile-import-reviewed"]').setValue(true)
  await wrapper.find('[data-testid="confirm-import"]').trigger('click')
  await flushPromises()
  expect(confirmProfileImport).toHaveBeenCalledOnce()
  expect(onChanged).toHaveBeenCalledTimes(1)
})

it('部分候选会明确展示遗漏条目和未映射字段', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue({
    ...candidate,
    completeness: { status: 'PARTIAL', valid_item_count: 1, rejected_item_count: 1, unmapped_field_count: 1 },
    rejected_items: [{
      group: 'experiences', index: 0, code: 'EVIDENCE_INVALID', fields: [],
      message: '该条目的字段或摘录无法逐字定位到简历原文，未进入待确认列表。',
    }],
    warnings: [{
      group: 'projects', index: 0, code: 'UNMAPPED_MODEL_FIELD', fields: ['deliverables'],
      message: '模型返回了当前档案结构未支持的字段；这些字段未作为候选事实导入。',
    }],
  })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: [new File(['<html>张三 熟悉 Python</html>'], 'sample.html', { type: 'text/html' })],
  })
  await input.trigger('change')
  await wrapper.find('[data-testid="profile-import-consent"]').setValue(true)
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await new Promise(resolve => setTimeout(resolve, 30))
  await flushPromises()

  const warning = wrapper.find('[data-testid="profile-import-partial-warning"]')
  expect(warning.exists()).toBe(true)
  expect(warning.text()).toContain('本次仅生成部分可验证候选')
  expect(warning.text()).toContain('experiences 第 1 条')
  expect(warning.text()).toContain('deliverables 未映射')
})

it('预览中的候选可以修正，确认时提交修正后的内容与项目选择', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue({
    ...candidate,
    candidate: {
      ...candidate.candidate,
      projects: [
        {
          name: '订单系统重构', role: null, description: null, responsibilities: null, achievements: null,
          tech_stack: [], url: null, start_date: null, end_date: null, source_quote: '订单系统重构',
        },
      ],
    },
  })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: [new File(['<html>张三 熟悉 Python 订单系统重构</html>'], 'sample.html', { type: 'text/html' })],
  })
  await input.trigger('change')
  await wrapper.find('[data-testid="profile-import-consent"]').setValue(true)
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await new Promise(resolve => setTimeout(resolve, 30))
  await flushPromises()

  // 项目经历区块按候选渲染，且技能与项目名都可以在预览里改。
  // 选择器限定为文本输入（`input.ant-input`）：条目容器内还有复选框的 input，取第一个会命错元素。
  expect(wrapper.text()).toContain('项目经历（1）')
  await wrapper.find('[data-testid="candidate-item-skills-0"] input.ant-input').setValue('Python 3')
  await wrapper.find('[data-testid="candidate-item-projects-0"] input.ant-input').setValue('订单系统重构（自研）')
  await wrapper.find('[data-testid="profile-import-reviewed"]').setValue(true)
  await wrapper.find('[data-testid="confirm-import"]').trigger('click')
  await flushPromises()

  expect(confirmProfileImport).toHaveBeenCalledOnce()
  const payload = vi.mocked(confirmProfileImport).mock.calls[0][0]
  expect(payload.candidate.skills[0].name).toBe('Python 3')
  expect(payload.candidate.projects[0].name).toBe('订单系统重构（自研）')
  expect(payload.projectIndices).toEqual([0])
  // 摘录保持只读：它是来源凭证，不能被编辑成别的内容。
  expect(payload.candidate.projects[0].source_quote).toBe('订单系统重构')
})

it('生成期间展示后端报告的阶段并保持按钮忙碌', async () => {
  let finish: ((value: ProfileImportPreview) => void) | undefined
  vi.mocked(previewProfileImportStream).mockImplementation(async (_filename, _content, _consent, onProgress) => {
    onProgress('ai_request_started')
    return new Promise<ProfileImportPreview>(resolve => { finish = resolve })
  })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: [new File(['<html>张三</html>'], 'sample.html', { type: 'text/html' })],
  })
  await input.trigger('change')
  await wrapper.find('[data-testid="profile-import-consent"]').setValue(true)
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await new Promise(resolve => setTimeout(resolve, 30))
  await flushPromises()
  expect(wrapper.find('[data-testid="profile-import-progress"]').text()).toContain('模型正在生成候选')
  expect(wrapper.find('[data-testid="preview-import"]').attributes('disabled')).toBeDefined()
  finish?.(candidate)
  await flushPromises()
  expect(wrapper.find('[data-testid="profile-import-progress"]').exists()).toBe(false)
  expect(wrapper.find('[data-testid="profile-import-preview"]').exists()).toBe(true)
})
