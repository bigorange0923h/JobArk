/** @vitest-environment jsdom */
/** 当前与历史输入分离；只使用虚构材料。 */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import type { ComponentPublicInstance } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchJob, listSnapshots, saveSnapshot, updateJob, type JobOpportunity, type JobSnapshot } from '@/shared/api/job'
import { createApplication } from '@/shared/api/application'
import { listResumes, listVersions } from '@/shared/api/resume'
import { requestV1, ApiError } from '@/shared/api/client'
import JobDetailView from './JobDetailView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('./JobExclusionPanel.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/shared/api/job', () => ({ fetchJob: vi.fn(), listSnapshots: vi.fn(), saveSnapshot: vi.fn(), updateJob: vi.fn() }))
vi.mock('@/shared/api/resume', () => ({ listResumes: vi.fn(), listVersions: vi.fn() }))
vi.mock('@/shared/api/application', () => ({ createApplication: vi.fn() }))
vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), requestV1: vi.fn() }))
const snapshot = (id: string, posting_id: string): JobSnapshot => ({ id, posting_id, raw_jd: '  完整原文\n第二行  ', captured_at: '2026-01-01T00:00:00Z', created_at: '', content_hash: id, parsed_json: null, parse_status: 'NOT_REQUESTED', parser_version: null, failure_code: null })
const a = snapshot('a', 'p2'), b = snapshot('b', 'p1')
function fixture(): JobOpportunity {
  return { id: 'job', version: 1, created_at: '', updated_at: '', title: '示例岗位', location: null, employment_type: null, status: 'ACTIVE', notes: null, outsourcing_arrangement: null,
    company: { id: 'company', version: 1, created_at: '', updated_at: '', name: '示例公司', name_normalized: '', website_url: null, industry: null, nature_code: null, industry_code: null, location: null },
    postings: ['p1', 'p2'].map(id => ({ id, version: 1, created_at: '', updated_at: '', opportunity_id: 'job', source: 'MANUAL', external_id: null, canonical_url: id === 'p2' ? 'https://example.com/job' : null, current_snapshot_id: id === 'p2' ? 'a' : 'b', first_seen_at: '', last_seen_at: '', page_status: 'ACTIVE' })), latest_snapshot: a }
}
beforeEach(() => {
  vi.clearAllMocks(); vi.mocked(fetchJob).mockResolvedValue(fixture()); vi.mocked(listSnapshots).mockResolvedValue([b, a]); vi.mocked(listResumes).mockResolvedValue([]); vi.mocked(requestV1).mockResolvedValue([])
})
enableAutoUnmount(afterEach)
const open = async () => { const w = mount(JobDetailView, { props: { jobId: 'job' }, global: { stubs: { RouterLink: true } } }); await flushPromises(); return w }
describe('当前保存 JD', () => {
  it('编辑和解析默认一致，历史首项不覆盖当前，原文、链接与未知时间明确展示', async () => {
    const w = await open()
    expect(w.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="edit-posting"]').props('value')).toBe('p2')
    expect(w.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="snapshot-selection"]').props('value')).toBe('a')
    const card = w.find('[data-testid="current-jd"]')
    expect(card.text()).toContain('当前保存 JD'); expect(card.text()).toContain('未知（尚未实现）')
    expect(card.find('a').attributes('href')).toBe('https://example.com/job')
    expect(card.find('pre').element.textContent).toBe(a.raw_jd)
    expect(card.text()).not.toContain('Invalid Date')
  })
  it('用户声明的渠道与公司介绍能回读，手工录入不会显示为平台采集', async () => {
    const data = fixture()
    data.postings[1]!.source = 'MANUAL'
    data.postings[1]!.channel_name = '公司官网'
    data.company.description = '用户复制的公司介绍'
    vi.mocked(fetchJob).mockResolvedValue(data)
    const w = await open()
    expect(w.find('[data-testid="current-jd"]').text()).toContain('公司官网（手工录入）')
    expect(w.find('[data-testid="company-info"]').text()).toContain('用户复制的公司介绍')
  })
  it('历史选择无写入，刷新变化提示并保留选择', async () => {
    const w = await open()
    w.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="snapshot-selection"]').vm.$emit('update:value', 'b'); await flushPromises()
    const changed = fixture(); changed.latest_snapshot = snapshot('c', 'p2'); changed.postings[1]!.current_snapshot_id = 'c'
    vi.mocked(fetchJob).mockResolvedValue(changed); vi.mocked(listSnapshots).mockResolvedValue([changed.latest_snapshot, b, a])
    await w.find('[data-testid="refresh-job"]').trigger('click'); await flushPromises()
    expect(w.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="snapshot-selection"]').props('value')).toBe('b')
    expect(w.find('[data-testid="current-changed"]').exists()).toBe(true)
    expect(w.find('[data-testid="selected-jd"]').text()).toContain('历史内容')
    expect(saveSnapshot).not.toHaveBeenCalled(); expect(updateJob).not.toHaveBeenCalled()
  })
  it('申请绑定明确选择的历史快照', async () => {
    vi.mocked(listResumes).mockResolvedValue([{ id: 'resume', name: '示例简历' }] as never)
    vi.mocked(listVersions).mockResolvedValue([{ id: 'version', version_no: 1 }] as never)
    const w = await open()
    w.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="snapshot-selection"]').vm.$emit('update:value', 'b')
    w.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="resume-selection"]').vm.$emit('update:value', 'version'); await flushPromises()
    await w.find('[data-testid="create-application"]').trigger('click'); await flushPromises()
    expect(createApplication).toHaveBeenCalledWith(expect.objectContaining({ job_snapshot_id: 'b', resume_version_id: 'version' }))
  })
  it('无当前 JD 不以历史兜底，缺失链接明确说明', async () => {
    const data = fixture(); data.latest_snapshot = null; data.postings.forEach(p => { p.current_snapshot_id = null })
    vi.mocked(fetchJob).mockResolvedValue(data)
    const w = await open()
    expect(w.find('[data-testid="current-jd"]').text()).toContain('暂无当前保存 JD')
    expect(w.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="snapshot-selection"]').props('value')).toBe('')
    expect(w.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="edit-posting"]').props('value')).toBe('')
    expect(w.text()).toContain('无原始链接')
  })
  it('当前来源无链接及无效时间明确显示未知，渠道不推断为手工', async () => {
    const data = fixture(); data.postings[1]!.source = 'FIFTYONEJOB'; data.postings[1]!.canonical_url = null
    data.postings[1]!.last_seen_at = '无效日期'
    vi.mocked(fetchJob).mockResolvedValue(data)
    const w = await open(); const current = w.find('[data-testid="current-jd"]')
    expect(current.text()).toContain('51job'); expect(current.text()).toContain('无原始链接')
    expect(current.find('a').exists()).toBe(false)
    expect(current.text()).toContain('系统最近接收内容时间：未知')
    expect(current.text()).not.toContain('Invalid Date')
  })
  it('刷新失败保留错误而不是空态，重试不替换已选择历史', async () => {
    const w = await open()
    w.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="snapshot-selection"]').vm.$emit('update:value', 'b'); await flushPromises()
    vi.mocked(listSnapshots).mockRejectedValueOnce(new ApiError({ code: 'NETWORK_ERROR', message: '历史读取失败' }))
    await w.find('[data-testid="refresh-job"]').trigger('click'); await flushPromises()
    expect(w.find('[data-testid="load-error"]').text()).toContain('历史读取失败')
    expect(w.find('[data-testid="current-jd"]').exists()).toBe(false)
    await w.find('[data-testid="retry-load"]').trigger('click'); await flushPromises()
    expect(w.getComponent<ComponentPublicInstance<{ value: string }>>('[data-testid="snapshot-selection"]').props('value')).toBe('b')
  })
  it('加载失败保留错误编号，不显示为空数据', async () => {
    vi.mocked(fetchJob).mockRejectedValue(new ApiError({ code: 'NETWORK_ERROR', message: '读取失败', requestId: 'request-example' }))
    const w = await open(); expect(w.find('[data-testid="load-error"]').text()).toContain('request-example')
    expect(w.find('[data-testid="current-jd"]').exists()).toBe(false)
  })
})
