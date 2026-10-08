/** @vitest-environment jsdom */

/** 匹配页错误反馈分流：加载失败留在页面，生成动作的网络失败走全局通知。 */
import { flushPromises, mount } from '@vue/test-utils'
import { notification } from 'ant-design-vue'
import type { ComponentPublicInstance } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, requestV1 } from '@/shared/api/client'
import { fetchJob, listJobs, listSnapshots } from '@/shared/api/job'
import { listResumes } from '@/shared/api/resume'
import { fetchProfile } from '@/shared/api/profile'

import MatchingView from './MatchingView.vue'

const noticeSpy = vi.spyOn(notification, 'error')

vi.mock('@/shared/api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('@/shared/api/client')>()
  return { ...actual, requestV1: vi.fn() }
})

vi.mock('@/shared/api/job', async importOriginal => {
  const actual = await importOriginal<typeof import('@/shared/api/job')>()
  return { ...actual, listJobs: vi.fn(), fetchJob: vi.fn(), listSnapshots: vi.fn() }
})

vi.mock('@/shared/api/resume', async importOriginal => {
  const actual = await importOriginal<typeof import('@/shared/api/resume')>()
  return { ...actual, listResumes: vi.fn(), listVersions: vi.fn() }
})

vi.mock('@/shared/api/profile', () => ({ fetchProfile: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))

beforeEach(() => {
  vi.clearAllMocks()
  noticeSpy.mockImplementation(() => undefined)
  vi.mocked(listJobs).mockResolvedValue([])
  vi.mocked(listResumes).mockResolvedValue([])
  vi.mocked(fetchProfile).mockResolvedValue({} as never)
  vi.mocked(requestV1).mockImplementation(async path => {
    if (path === '/matches') return [] as never
    if (path === '/profile/revisions') return [] as never
    if (path.includes('/parses')) return [] as never
    throw new Error(`未处理的请求：${path}`)
  })
})

describe('MatchingView', () => {
  it('新报告展示补充入口和出处支持程度，不把关联来源当作独立核验', async () => {
    vi.mocked(requestV1).mockImplementation(async path => {
      if (path === '/matches') return [{ id: 'report', created_at: '2026-01-01', match_kind: 'PROFILE',
        job_snapshot_id: 'snapshot', profile_revision_id: 'revision', resume_version_id: null,
        report_json: { reference_score: { lower: 2, upper: 8, coverage: 0.3, single_score: null,
          recommendation: '先补充/确认信息', conditions: [] }, data_warnings: ['请确认薪资口径'],
          requirements: [{ text: '本科或相关经验', relation: 'OR', source_start: 0, source_end: 8, hard: false,
            status: 'UNKNOWN', explanation: '需核对', evidence: [{ fact_id: 'fact', name: '项目',
              claim_status: 'UNVERIFIED', evidence_title: '简历摘录', fact_quote: '核心开发', source_support: 'SOURCE_ATTACHED' }] }],
          uncertainties: [] } }] as never
      return [] as never
    })
    const wrapper = mount(MatchingView, { global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } } })
    await flushPromises()
    await wrapper.get('.ant-collapse-header').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="data-warnings"]').text()).toContain('请确认薪资口径')
    expect(wrapper.text()).toContain('有关联来源，当前摘录未覆盖这一判断')
    expect(wrapper.text()).toContain('替代条件（待确认）')
    expect(wrapper.find('a[href="/profile"]').exists()).toBe(true)
    expect(wrapper.find('a[href="/strategy"]').exists()).toBe(true)
    wrapper.unmount()
  })
  it('默认明确当前 JD，当前缺失时不以历史首项兜底', async () => {
    vi.mocked(fetchJob).mockResolvedValue({ latest_snapshot: { id: 'current', posting_id: 'source', captured_at: '2026-01-01T00:00:00Z' } } as never)
    vi.mocked(listSnapshots).mockResolvedValue([{ id: 'history', captured_at: '2026-02-01T00:00:00Z' }, { id: 'current', captured_at: '2026-01-01T00:00:00Z' }] as never)
    const wrapper = mount(MatchingView)
    await flushPromises()
    const choice = wrapper.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="matching-job"]')
    choice.vm.$emit('update:value', 'job'); choice.vm.$emit('change', 'job'); await flushPromises()
    expect(wrapper.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="matching-snapshot"]').props('value')).toBe('current')
    vi.mocked(fetchJob).mockResolvedValue({ latest_snapshot: null } as never)
    choice.vm.$emit('update:value', 'missing'); choice.vm.$emit('change', 'missing'); await flushPromises()
    expect(wrapper.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="matching-snapshot"]').props('value')).toBe('')
    wrapper.unmount()
  })
  it('初始加载失败保留页面内错误与重试入口，不弹全局通知', async () => {
    vi.mocked(listJobs).mockRejectedValue(
      new ApiError({ code: 'NETWORK_ERROR', message: '无法连接到服务，请确认后端是否已启动。' }),
    )

    const wrapper = mount(MatchingView)
    await flushPromises()

    expect(wrapper.find('[data-testid="load-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="retry-load"]').exists()).toBe(true)
    expect(noticeSpy).not.toHaveBeenCalled()
  })

  it('生成报告的网络失败只弹一次全局通知，不插入操作错误块', async () => {
    vi.mocked(requestV1).mockImplementation(async (path, options) => {
      if (path === '/matches' && options?.init?.method === 'POST') {
        throw new ApiError({ code: 'NETWORK_ERROR', message: '无法连接到服务，请确认后端是否已启动。' })
      }
      if (path === '/profile/revisions' && options?.init?.method === 'POST') return { id: 'revision' } as never
      if (path.includes('/parses')) return { id: 'parse' } as never
      if (path === '/matches' || path === '/profile/revisions') return [] as never
      throw new Error(`未处理的请求：${path}`)
    })
    const wrapper = mount(MatchingView)
    await flushPromises()

    // 按钮禁用只保护真实交互；直接触发表单提交可以验证分析逻辑本身的失败分流。
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(noticeSpy).toHaveBeenCalledTimes(1)
    expect(noticeSpy.mock.calls[0][0]).toMatchObject({ message: '生成匹配报告失败' })
    expect(wrapper.find('[data-testid="action-error"]').exists()).toBe(false)
  })
})
