/** @vitest-environment jsdom */

import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { notification } from 'ant-design-vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { createManualJob, listJobs, type JobListItem, type JobOpportunity } from '@/shared/api/job'

import JobListView from './JobListView.vue'

/**
 * 全局通知的落点在这里被拦截：组件不直接调用通知 API，断言实际弹出的通知才能验证
 * "422 只内联、网络错误只弹一次"这类分流规则没有被绕过。
 */
const noticeSpy = vi.spyOn(notification, 'error')

vi.mock('@/shared/api/job', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/job')>()
  return { ...actual, listJobs: vi.fn(), createManualJob: vi.fn() }
})

function listItem(): JobListItem {
  return { id: 'job-1', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', version: 1, company_name: '示例科技', title: '后端工程师', location: '上海', employment_type: '全职', status: 'ACTIVE', latest_snapshot_id: 'snapshot-1', latest_captured_at: '2026-01-01T00:00:00Z' }
}

beforeEach(() => {
  vi.clearAllMocks()
  noticeSpy.mockImplementation(() => undefined)
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
    expect(wrapper.text()).toContain('当前 JD 首次采集')
    expect(wrapper.text()).not.toContain('最近 JD')
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

  it('雇佣类型优先给出常见和历史选项，也允许手动填写其他类型', async () => {
    vi.mocked(listJobs).mockResolvedValueOnce([{ ...listItem(), employment_type: '学徒制' }])
    const wrapper = mount(JobListView)
    await flushPromises()
    const employment = wrapper.findComponent({ name: 'AAutoComplete' })
    expect(employment.props('options')).toContainEqual({ value: '全职', label: '全职' })
    expect(employment.props('options')).toContainEqual({ value: '学徒制', label: '学徒制' })
    employment.vm.$emit('update:value', '灵活用工')
    await wrapper.find('[data-testid="company-name"]').setValue('示例科技')
    await wrapper.find('[data-testid="job-title"]').setValue('后端工程师')
    await wrapper.find('[data-testid="raw-jd"]').setValue('真实 JD')
    await wrapper.find('[data-testid="create-job"]').trigger('click')
    expect(createManualJob).toHaveBeenCalledWith(expect.objectContaining({ employment_type: '灵活用工' }))
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
    // 422 需要用户就地修改字段，不能被自动消失的通知替代。
    expect(wrapper.find('[data-testid="form-error"]').exists()).toBe(true)
    expect(noticeSpy).not.toHaveBeenCalled()
  })

  it('网络错误只弹一次通知，不再插入页面内错误块', async () => {
    vi.mocked(createManualJob).mockRejectedValue(
      new ApiError({ code: 'NETWORK_ERROR', message: '无法连接到服务，请确认后端是否已启动。' }),
    )
    const wrapper = mount(JobListView)
    await flushPromises()
    await wrapper.find('[data-testid="company-name"]').setValue('示例科技')
    await wrapper.find('[data-testid="job-title"]').setValue('后端工程师')
    await wrapper.find('[data-testid="raw-jd"]').setValue('真实 JD')

    await wrapper.find('[data-testid="create-job"]').trigger('click')
    await flushPromises()
    // 第二次是同一个动作的相同失败：去重窗口内不再叠加第二条通知。
    await wrapper.find('[data-testid="create-job"]').trigger('click')
    await flushPromises()

    expect(noticeSpy).toHaveBeenCalledTimes(1)
    expect(noticeSpy.mock.calls[0][0]).toMatchObject({ message: '保存职位失败', placement: 'topRight', duration: 5 })
    expect(String(noticeSpy.mock.calls[0][0].description)).toContain('无法连接到服务')
    expect(wrapper.find('[data-testid="form-error"]').exists()).toBe(false)
  })

  it('加载失败保留页面内提示与刷新入口，且不弹通知', async () => {
    vi.mocked(listJobs).mockRejectedValue(
      new ApiError({ code: 'INTERNAL_ERROR', message: '服务器内部错误，请稍后重试。', status: 500, requestId: 'req-load' }),
    )
    const wrapper = mount(JobListView)
    await flushPromises()

    expect(wrapper.find('[data-testid="load-error"]').text()).toContain('服务器内部错误')
    expect(wrapper.find('[data-testid="reload"]').exists()).toBe(true)
    expect(noticeSpy).not.toHaveBeenCalled()
  })
})
