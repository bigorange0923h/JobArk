/** @vitest-environment jsdom */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { listApplications, fetchApplication, transitionApplication, type ApplicationDetail } from '@/shared/api/application'
import { listJobs } from '@/shared/api/job'
import { fetchVersion, type ResumeVersion } from '@/shared/api/resume'
import { ApiError } from '@/shared/api/client'
import { router } from '@/app/router'
import ApplicationView from './ApplicationView.vue'

vi.mock('@/shared/api/application', async importOriginal => ({
  ...await importOriginal<typeof import('@/shared/api/application')>(),
  listApplications: vi.fn(), fetchApplication: vi.fn(), transitionApplication: vi.fn(),
}))
vi.mock('@/shared/api/job', () => ({ listJobs: vi.fn() }))
vi.mock('@/shared/api/resume', () => ({ fetchVersion: vi.fn() }))
enableAutoUnmount(afterEach)

const detail = {
  id: 'a1', job_opportunity_id: 'j1', resume_version_id: 'v1', attempt_no: 1,
  version: 1, current_status: 'SAVED', events: [], allowed_statuses: ['APPLIED'],
} as unknown as ApplicationDetail

async function chooseApplied(wrapper: ReturnType<typeof mount>): Promise<void> {
  await wrapper.find('[data-testid="next-status"] .ant-select-selector').trigger('mousedown')
  await flushPromises()
  const option = Array.from(document.querySelectorAll('.ant-select-item-option')).find(node => node.textContent?.includes('已投递'))
  expect(option).toBeTruthy()
  ;(option as HTMLElement).click()
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listApplications).mockResolvedValue([detail])
  vi.mocked(listJobs).mockResolvedValue([])
  vi.mocked(fetchApplication).mockResolvedValue(detail)
  vi.mocked(fetchVersion).mockResolvedValue({id:'v1', resume_id:'r1', version_no:1} as ResumeVersion)
})

it('已投递需要显式确认；绑定历史版本可回看', async () => {
  // 必须注入真实 router：`RouterLink` 在未安装 router 时无法解析，会渲染成注释节点，
  // 断言 `a[href=...]` 会退化成"永远为 false"的假失败。
  const wrapper = mount(ApplicationView, { global: { plugins: [router] } })
  await flushPromises()
  await wrapper.find('tbody button').trigger('click')
  await flushPromises()
  expect(wrapper.find('a[href="/resumes/r1/preview?version=v1"]').exists()).toBe(true)
  await chooseApplied(wrapper)
  expect(wrapper.find('[data-testid="save-transition"]').attributes('disabled')).toBeDefined()
  await wrapper.find('input[type="checkbox"]').setValue(true)
  await flushPromises()
  vi.mocked(transitionApplication).mockResolvedValue({...detail, version:2, current_status:'APPLIED'})
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(transitionApplication).toHaveBeenCalledWith('a1', {version:1, status:'APPLIED', confirm_applied:true, notes:null})
}, 15_000)

it('冲突时保留备注并显示错误，不伪造时间线', async () => {
  const wrapper = mount(ApplicationView, { global: { plugins: [router] } })
  await flushPromises()
  await wrapper.find('tbody button').trigger('click')
  await flushPromises()
  await chooseApplied(wrapper)
  await wrapper.find('input[type="checkbox"]').setValue(true)
  await flushPromises()
  await wrapper.find('textarea').setValue('测试备注')
  vi.mocked(transitionApplication).mockRejectedValue(new ApiError({code:'CONFLICT', message:'版本已过期', status:409}))
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(wrapper.find('[role=alert]').text()).toContain('版本已过期')
  expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('测试备注')
  expect(wrapper.findAll('.ant-timeline-item')).toHaveLength(0)
})
