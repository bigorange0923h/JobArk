/** @vitest-environment jsdom */
/** 公司报告的未配置、身份确认、外发取消和独立失败展示。 */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { requestV1, ApiError } from '@/shared/api/client'
import { fetchJob } from '@/shared/api/job'
import CompanyResearchPanel from './CompanyResearchPanel.vue'

vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), requestV1: vi.fn() }))
vi.mock('@/shared/api/job', () => ({ fetchJob: vi.fn() }))
enableAutoUnmount(afterEach)
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchJob).mockResolvedValue({ company: null } as never)
  vi.mocked(requestV1).mockImplementation(async path => {
    if (path.endsWith('/capabilities')) return { configured: false, provider: '测试搜索', endpoint: '', queries: 6, sources: 8, total_seconds: 90 } as never
    return [] as never
  })
})

it('无公司身份和未配置时明确提示，不自动搜索或编造通过结论', async () => {
  const wrapper = mount(CompanyResearchPanel, { props: { jobId: 'j1' } })
  await flushPromises()
  expect(wrapper.text()).toContain('尚未配置')
  expect(wrapper.text()).toContain('不代表公司已通过尽调')
  expect(vi.mocked(requestV1).mock.calls.every(([, options]) => !options?.init?.method)).toBe(true)
})

it('查询失败保留用户核对输入并显示安全错误编号', async () => {
  const wrapper = mount(CompanyResearchPanel, { props: { jobId: 'j1' } })
  await flushPromises()
  await wrapper.find('input').setValue('待确认公司')
  vi.mocked(requestV1).mockRejectedValueOnce(new ApiError({ code: 'CONFLICT', message: '策略排除，外部查询停止', status: 409, requestId: 'r1' }))
  await wrapper.findAll('button').find(button => button.text().includes('记录待确认'))!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('外部查询停止')
  expect(wrapper.text()).toContain('r1')
  expect((wrapper.find('input').element as HTMLInputElement).value).toBe('待确认公司')
  expect(vi.mocked(requestV1).mock.calls.at(-1)?.[1]?.init?.body).toContain('"confirm_external":false')
})

it('部分报告展示未知、来源和失败，不误报通过尽调', async () => {
  vi.mocked(requestV1).mockImplementation(async path => path.endsWith('/capabilities') ? { configured: true } as never : [{ id: 'r', status: 'PARTIAL', created_at: '2026-01-01T00:00:00Z', age_seconds: 90000, report_json: { sources: [], findings: [], failure_codes: ['SUMMARY_UNAVAILABLE'] } }] as never)
  const wrapper = mount(CompanyResearchPanel, { props: { jobId: 'j1' } })
  await flushPromises()
  expect(wrapper.text()).toContain('部分来源，仍需核对')
  await wrapper.find('[role="button"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('SUMMARY_UNAVAILABLE')
  expect(wrapper.text()).toContain('超过 24 小时')
})
