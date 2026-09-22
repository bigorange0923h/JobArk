/**
 * @vitest-environment jsdom
 *
 * 简历方向列表页的状态与写入测试。
 *
 * 覆盖三类容易写错的地方：
 *
 * - 加载失败与"列表为空"必须区分：空列表是正常状态，不是错误；
 * - 创建失败时**保留用户输入**：把已经敲好的名称清掉会让用户重打一遍，而失败原因往往只是重名；
 * - 归档后必须重新拉取列表：只把本地那一行删掉，会与后端的"默认列表不含已归档"规则各说一套。
 */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { archiveResume, createResume, listResumes, type Resume } from '@/shared/api/resume'

import ResumeListView from './ResumeListView.vue'

const { push } = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

// 只替换本页真正调用的接口；类型与枚举保持真实，避免测试用的替身与真实契约脱节。
vi.mock('@/shared/api/resume', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/resume')>()
  return {
    ...actual,
    listResumes: vi.fn(),
    createResume: vi.fn(),
    archiveResume: vi.fn(),
  }
})

/** 一份简历方向。 */
function resumeFixture(overrides: Partial<Resume> = {}): Resume {
  return {
    id: 'resume-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
    name: 'Java 后端',
    target_direction: '后端',
    status: 'ACTIVE',
    ...overrides,
  }
}

function mountView(): VueWrapper {
  return mount(ResumeListView)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listResumes).mockResolvedValue([resumeFixture()])
  vi.mocked(createResume).mockResolvedValue(resumeFixture({ id: 'resume-2', name: 'AI 应用' }))
  vi.mocked(archiveResume).mockResolvedValue(resumeFixture({ status: 'ARCHIVED' }))
})

enableAutoUnmount(afterEach)

describe('ResumeListView', () => {
  it('加载失败时显示后端提示与错误编号，而不是空列表', async () => {
    vi.mocked(listResumes).mockRejectedValueOnce(
      new ApiError({
        code: 'NETWORK_ERROR',
        message: '无法连接到服务，请确认后端是否已启动。',
        requestId: 'req-resume',
      }),
    )

    const wrapper = mountView()
    await flushPromises()

    const alert = wrapper.find('[data-testid="load-error"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('无法连接到服务，请确认后端是否已启动。')
    expect(alert.text()).toContain('req-resume')
  })

  it('加载成功后列出方向名称与目标方向', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Java 后端')
    expect(wrapper.text()).toContain('后端')
    expect(wrapper.find('[data-testid="load-error"]').exists()).toBe(false)
  })

  it('创建成功后重新拉取列表并清空输入', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="resume-name"]').setValue('AI 应用')
    await wrapper.find('[data-testid="create-resume"]').trigger('click')
    await flushPromises()

    expect(createResume).toHaveBeenCalledWith({ name: 'AI 应用', target_direction: null })
    expect((wrapper.find('[data-testid="resume-name"]').element as HTMLInputElement).value).toBe('')
    // 新建后必须重新拉取：新行由后端生成，本地拼一行会漏掉后端补的字段。
    expect(listResumes).toHaveBeenCalledTimes(2)
  })

  it('同名冲突时显示后端文案，并保留已填写的名称', async () => {
    vi.mocked(createResume).mockRejectedValueOnce(
      new ApiError({ code: 'CONFLICT', message: '已存在同名简历方向。', status: 409 }),
    )
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="resume-name"]').setValue('Java 后端')
    await wrapper.find('[data-testid="create-resume"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="form-error"]').text()).toContain('已存在同名简历方向。')
    expect((wrapper.find('[data-testid="resume-name"]').element as HTMLInputElement).value).toBe('Java 后端')
  })

  it('未填写名称时不提交', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="create-resume"]').trigger('click')
    await flushPromises()

    expect(createResume).not.toHaveBeenCalled()
  })

  it('归档后重新拉取列表，而不是就地删掉那一行', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.findComponent({ name: 'APopconfirm' }).vm.$emit('confirm')
    await flushPromises()

    expect(archiveResume).toHaveBeenCalledWith('resume-1')
    expect(listResumes).toHaveBeenCalledTimes(2)
  })

  it('点击打开会按主键跳转到详情页', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="open-resume-1"]').trigger('click')

    expect(push).toHaveBeenCalledWith({ name: 'resume-detail', params: { resumeId: 'resume-1' } })
  })
})
