/** @vitest-environment jsdom */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { listApplications, fetchApplication, transitionApplication, type ApplicationDetail } from '@/shared/api/application'
import { listJobs } from '@/shared/api/job'
import { fetchVersion, type ResumeVersion } from '@/shared/api/resume'
import { ApiError } from '@/shared/api/client'
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

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listApplications).mockResolvedValue([detail])
  vi.mocked(listJobs).mockResolvedValue([])
  vi.mocked(fetchApplication).mockResolvedValue(detail)
  vi.mocked(fetchVersion).mockResolvedValue({id:'v1', resume_id:'r1', version_no:1} as ResumeVersion)
})

it('已投递需要显式确认；绑定历史版本可回看', async () => {
  const wrapper = mount(ApplicationView, { global: { stubs: { RouterLink: { template:'<a :href="to"><slot /></a>', props:['to'] } } } })
  await flushPromises()
  await wrapper.find('tbody button').trigger('click')
  await flushPromises()
  expect(wrapper.find('a[href="/resumes/r1/preview?version=v1"]').exists()).toBe(true)
  await wrapper.find('select').setValue('APPLIED')
  expect(wrapper.find('input[type=checkbox]').attributes('required')).toBeDefined()
  await wrapper.find('input[type=checkbox]').setValue(true)
  vi.mocked(transitionApplication).mockResolvedValue({...detail, version:2, current_status:'APPLIED'})
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(transitionApplication).toHaveBeenCalledWith('a1', {version:1, status:'APPLIED', confirm_applied:true, notes:null})
})

it('冲突时保留备注并显示错误，不伪造时间线', async () => {
  const wrapper = mount(ApplicationView, { global: { stubs: { RouterLink:true } } })
  await flushPromises()
  await wrapper.find('tbody button').trigger('click')
  await flushPromises()
  await wrapper.find('select').setValue('APPLIED')
  await wrapper.find('textarea').setValue('测试备注')
  vi.mocked(transitionApplication).mockRejectedValue(new ApiError({code:'CONFLICT', message:'版本已过期', status:409}))
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(wrapper.find('[role=alert]').text()).toContain('版本已过期')
  expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('测试备注')
  expect(wrapper.findAll('ol li')).toHaveLength(0)
})
