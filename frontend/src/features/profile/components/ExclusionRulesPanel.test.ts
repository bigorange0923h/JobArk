/** @vitest-environment jsdom */
/** 排除规则编辑器须明确保存后才写入正式规则。 */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { getExclusionPolicy, listJobs, saveExclusionPolicy, type ExclusionPolicy } from '@/shared/api/job'
import ExclusionRulesPanel from './ExclusionRulesPanel.vue'

vi.mock('@/shared/api/job', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/job')>()
  return { ...actual, getExclusionPolicy: vi.fn(), listJobs: vi.fn(), saveExclusionPolicy: vi.fn() }
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getExclusionPolicy).mockResolvedValue({ version: 0, rules: [] })
  vi.mocked(listJobs).mockResolvedValue([])
  vi.mocked(saveExclusionPolicy).mockImplementation(async payload => ({ ...payload, version: 1 }))
})
enableAutoUnmount(afterEach)

it('只把用户分类添加并保存为正式规则，启停状态随版本保存', async () => {
  const wrapper = mount(ExclusionRulesPanel)
  await flushPromises()
  const inputs = wrapper.findAll('input')
  const nameInput = inputs.find(input => input.attributes('placeholder') === '输入完整名称或关键词')
  expect(nameInput).toBeDefined()
  await nameInput!.setValue('同名公司')
  await wrapper.find('[data-testid="add-rule-COMPANY_NAME"]').trigger('click')
  await flushPromises()
  expect(saveExclusionPolicy).not.toHaveBeenCalled()
  await wrapper.find('[data-testid="save-exclusion-rules"]').trigger('click')
  await flushPromises()
  expect(saveExclusionPolicy).toHaveBeenCalledWith(expect.objectContaining({
    version: 0,
    rules: [expect.objectContaining({ kind: 'COMPANY_NAME', value: '同名公司', enabled: true })],
  }) as ExclusionPolicy)
})
