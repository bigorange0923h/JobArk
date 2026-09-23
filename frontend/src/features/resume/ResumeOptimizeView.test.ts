/** @vitest-environment jsdom */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { requestV1, ApiError } from '@/shared/api/client'
import { listVersions, type ResumeVersion } from '@/shared/api/resume'
import { createBlankDocument } from './document'
import ResumeOptimizeView from './ResumeOptimizeView.vue'

async function fillRequest(wrapper: ReturnType<typeof mount>): Promise<void> {
  await wrapper.find('[data-testid="base-version"] .ant-select-selector').trigger('mousedown')
  await flushPromises()
  const option = Array.from(document.querySelectorAll('.ant-select-item-option')).find(node => node.textContent?.includes('版本 1'))
  expect(option).toBeTruthy()
  ;(option as HTMLElement).click()
  await wrapper.find('[data-testid="target-direction"]').setValue('后端开发')
  await wrapper.find('input[type="checkbox"]').setValue(true)
  await flushPromises()
}

vi.mock('@/shared/api/client', async importOriginal => ({
  ...await importOriginal<typeof import('@/shared/api/client')>(), requestV1: vi.fn(),
}))
vi.mock('@/shared/api/resume', () => ({ listVersions: vi.fn() }))
enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.clearAllMocks()
  const document = createBlankDocument()
  document.basics.full_name = '测试姓名'
  vi.mocked(listVersions).mockResolvedValue([{id:'v1', version_no:1, document_json:document} as ResumeVersion])
})

it('明确确认外部发送后生成候选，显示双侧预览而非自动确认', async () => {
  const wrapper = mount(ResumeOptimizeView, { props:{resumeId:'r1'}, global:{ stubs:{RouterLink:true} } })
  await flushPromises()
  expect(wrapper.find('button').attributes('disabled')).toBeDefined()
  await fillRequest(wrapper)
  const document = createBlankDocument()
  document.basics.full_name = '测试姓名'
  vi.mocked(requestV1).mockResolvedValue({id:'d1', base_resume_version_id:'v1', document_json:document})
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(requestV1).toHaveBeenCalledTimes(1)
  expect(wrapper.findAll('.comparison > article')).toHaveLength(2)
  expect(wrapper.text()).toContain('此候选尚未成为正式版本')
  expect(wrapper.find('pre').exists()).toBe(false)
})

it('网关不可用时保留目标与基线，不出现虚假的候选', async () => {
  const wrapper = mount(ResumeOptimizeView, { props:{resumeId:'r1'}, global:{ stubs:{RouterLink:true} } })
  await flushPromises()
  await fillRequest(wrapper)
  vi.mocked(requestV1).mockRejectedValue(new ApiError({code:'CONFLICT', status:409, message:'尚未配置 AI 网关'}))
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(wrapper.find('.ant-alert-error').text()).toContain('尚未配置 AI 网关')
  expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('后端开发')
  expect(wrapper.find('.comparison').exists()).toBe(false)
})
