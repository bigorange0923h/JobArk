/** @vitest-environment jsdom */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { notification } from 'ant-design-vue'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { listApplications, fetchApplication, transitionApplication, changeApplicationMaterials, type ApplicationDetail } from '@/shared/api/application'
import { listJobs, listSnapshots } from '@/shared/api/job'
import { fetchVersion, listResumes, listVersions, type ResumeVersion } from '@/shared/api/resume'
import { ApiError } from '@/shared/api/client'
import { router } from '@/app/router'
import ApplicationView from './ApplicationView.vue'

/** 页面只通过统一入口弹通知，因此拦截通知调用即可验证"哪些失败不该弹通知"。 */
const noticeSpy = vi.spyOn(notification, 'error')

vi.mock('@/shared/api/application', async importOriginal => ({
  ...await importOriginal<typeof import('@/shared/api/application')>(),
  listApplications: vi.fn(), fetchApplication: vi.fn(), transitionApplication: vi.fn(), changeApplicationMaterials: vi.fn(),
}))
vi.mock('@/shared/api/job', () => ({ listJobs: vi.fn(), listSnapshots: vi.fn() }))
vi.mock('@/shared/api/resume', () => ({ fetchVersion: vi.fn(), listResumes: vi.fn(), listVersions: vi.fn() }))
enableAutoUnmount(afterEach)

const detail = {
  id: 'a1', job_opportunity_id: 'j1', job_snapshot_id: 's1', material_locked_at: null, resume_version_id: 'v1', attempt_no: 1,
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
  noticeSpy.mockImplementation(() => undefined)
  vi.mocked(listApplications).mockResolvedValue([detail])
  vi.mocked(listJobs).mockResolvedValue([])
  vi.mocked(listSnapshots).mockResolvedValue([])
  vi.mocked(listResumes).mockResolvedValue([])
  vi.mocked(listVersions).mockResolvedValue([])
  vi.mocked(fetchApplication).mockResolvedValue(detail)
  vi.mocked(fetchVersion).mockResolvedValue({id:'v1', resume_id:'r1', version_no:1} as ResumeVersion)
})

it('已投递需要在二次弹窗显式确认；绑定历史版本可回看', async () => {
  // 必须注入真实 router：`RouterLink` 在未安装 router 时无法解析，会渲染成注释节点，
  // 断言 `a[href=...]` 会退化成"永远为 false"的假失败。
  const wrapper = mount(ApplicationView, { global: { plugins: [router] } })
  await flushPromises()
  await wrapper.find('tbody button').trigger('click')
  await flushPromises()
  expect(wrapper.find('a[href="/resumes/r1/preview?version=v1"]').exists()).toBe(true)
  await chooseApplied(wrapper)
  expect(wrapper.find('[data-testid="save-transition"]').attributes('disabled')).toBeUndefined()
  await wrapper.find('[data-testid="save-transition"]').trigger('click')
  await flushPromises()
  expect(document.querySelector('[data-testid="confirm-applied-dialog"]')).toBeTruthy()
  expect(transitionApplication).not.toHaveBeenCalled()
  vi.mocked(transitionApplication).mockResolvedValue({...detail, version:2, current_status:'APPLIED'})
  await wrapper.findComponent({ name: 'AModal' }).vm.$emit('ok')
  await flushPromises()
  expect(transitionApplication).toHaveBeenCalledWith('a1', {version:1, status:'APPLIED', confirm_applied:true, notes:null})
}, 15_000)

it('冲突时保留备注并显示错误，不伪造时间线', async () => {
  const wrapper = mount(ApplicationView, { global: { plugins: [router] } })
  await flushPromises()
  await wrapper.find('tbody button').trigger('click')
  await flushPromises()
  await chooseApplied(wrapper)
  await wrapper.find('[data-testid="save-transition"]').trigger('click')
  await flushPromises()
  await wrapper.find('textarea').setValue('测试备注')
  vi.mocked(transitionApplication).mockRejectedValue(new ApiError({code:'CONFLICT', message:'版本已过期', status:409}))
  await wrapper.findComponent({ name: 'AModal' }).vm.$emit('ok')
  await flushPromises()
  expect(wrapper.find('[role=alert]').text()).toContain('版本已过期')
  expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('测试备注')
  expect(wrapper.findAll('.ant-timeline-item')).toHaveLength(0)
  // 409 是"基于当前界面就能理解并处理"的失败：必须留在操作上下文里，不能只弹通知。
  expect(wrapper.find('[data-testid="action-error"]').exists()).toBe(true)
  expect(noticeSpy).not.toHaveBeenCalled()
})

it('首次加载失败保留页面内提示与重新加载入口，且不弹通知', async () => {
  vi.mocked(listApplications).mockRejectedValue(
    new ApiError({ code: 'INTERNAL_ERROR', message: '服务器内部错误，请稍后重试。', status: 500, requestId: 'req-load' }),
  )
  const wrapper = mount(ApplicationView, { global: { plugins: [router] } })
  await flushPromises()

  const alert = wrapper.find('[data-testid="load-error"]')
  expect(alert.text()).toContain('服务器内部错误')
  expect(alert.text()).toContain('req-load')
  expect(wrapper.find('[data-testid="retry-load"]').exists()).toBe(true)
  expect(noticeSpy).not.toHaveBeenCalled()
})

it('读取时间线的网络错误只弹一次通知，不插入内联错误块', async () => {
  vi.mocked(fetchApplication).mockRejectedValue(
    new ApiError({ code: 'NETWORK_ERROR', message: '无法连接到服务，请确认后端是否已启动。' }),
  )
  const wrapper = mount(ApplicationView, { global: { plugins: [router] } })
  await flushPromises()

  await wrapper.find('tbody button').trigger('click')
  await flushPromises()
  // 再次点击同一入口：相同动作与相同错误在去重窗口内只提示一次。
  await wrapper.find('tbody button').trigger('click')
  await flushPromises()

  expect(noticeSpy).toHaveBeenCalledTimes(1)
  expect(noticeSpy.mock.calls[0][0]).toMatchObject({ message: '读取申请时间线失败' })
  expect(wrapper.find('[data-testid="action-error"]').exists()).toBe(false)
  expect(wrapper.find('[data-testid="load-error"]').exists()).toBe(false)
})


it('无简历也可查看准备记录；保存材料采用新投影', async () => {
  vi.mocked(fetchApplication).mockResolvedValue({ ...detail, resume_version_id: null })
  vi.mocked(changeApplicationMaterials).mockResolvedValue({ ...detail, resume_version_id: null, version: 2 })
  const wrapper = mount(ApplicationView, { global: { plugins: [router] } })
  await flushPromises()
  await wrapper.find('tbody button').trigger('click'); await flushPromises()
  expect(fetchVersion).not.toHaveBeenCalled()
  const save = wrapper.findAll('button').find(button => button.text() === '保存材料')
  await save?.trigger('click'); await flushPromises()
  expect(changeApplicationMaterials).toHaveBeenCalledWith('a1', { version: 1, job_snapshot_id: 's1', resume_version_id: null })
})
