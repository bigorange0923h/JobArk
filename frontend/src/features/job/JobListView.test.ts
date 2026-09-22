/** @vitest-environment jsdom */

import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { createManualJob, listJobs, type JobListItem, type JobOpportunity } from '@/shared/api/job'

import JobListView from './JobListView.vue'

vi.mock('@/shared/api/job', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/job')>()
  return { ...actual, listJobs: vi.fn(), createManualJob: vi.fn() }
})

function listItem(): JobListItem {
  return { id: 'job-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', version: 1, company_name: '示例科技', title: '后端工程师', location: '上海', employment_type: '全职', status: 'ACTIVE', latest_snapshot_id: 'snapshot-1', latest_captured_at: '2026-01-01T00:00:00Z' }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listJobs).mockResolvedValue([listItem()])
  vi.mocked(createManualJob).mockResolvedValue({} as JobOpportunity)
})

enableAutoUnmount(afterEach)

describe('JobListView', () => {
  it('读取并展示职位摘要', async () => {
    const wrapper = mount(JobListView)
    await flushPromises()
    expect(wrapper.text()).toContain('示例科技')
    expect(wrapper.text()).toContain('后端工程师')
  })

  it('只在三个必填字段齐全时提交，成功后刷新并清空输入', async () => {
    const wrapper = mount(JobListView)
    await flushPromises()
    await wrapper.find('[data-testid="company-name"]').setValue('示例科技')
    await wrapper.find('[data-testid="job-title"]').setValue('后端工程师')
    await wrapper.find('[data-testid="raw-jd"]').setValue(' 真实 JD\n')
    await wrapper.find('[data-testid="create-job"]').trigger('click')
    await flushPromises()
    expect(createManualJob).toHaveBeenCalledWith(expect.objectContaining({ title: '后端工程师', raw_jd: ' 真实 JD\n' }))
    expect(listJobs).toHaveBeenCalledTimes(2)
    expect((wrapper.find('[data-testid="company-name"]').element as HTMLInputElement).value).toBe('')
  })

  it('服务端拒绝时保留输入并显示原因', async () => {
    vi.mocked(createManualJob).mockRejectedValueOnce(new ApiError({ code: 'VALIDATION_ERROR', message: 'JD 无效。', status: 422 }))
    const wrapper = mount(JobListView)
    await flushPromises()
    await wrapper.find('[data-testid="company-name"]').setValue('示例科技')
    await wrapper.find('[data-testid="job-title"]').setValue('后端工程师')
    await wrapper.find('[data-testid="raw-jd"]').setValue('真实 JD')
    await wrapper.find('[data-testid="create-job"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="form-error"]').text()).toContain('JD 无效。')
    expect((wrapper.find('[data-testid="raw-jd"]').element as HTMLTextAreaElement).value).toBe('真实 JD')
  })
})
