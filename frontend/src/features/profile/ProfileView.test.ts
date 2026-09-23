/**
 * @vitest-environment jsdom
 *
 * 个人资料页的状态与错误处理测试。
 *
 * 覆盖四种页面状态中的三种（加载中由 `a-spin` 呈现，随其他用例一并验证），以及本页最容易出错
 * 的一条路径：乐观锁冲突。冲突的价值在于它是唯一必须"重新加载才能继续"的失败，测试要同时断言
 * 提示出现与聚合被重新拉取，只断言提示会漏掉"界面提示了但数据仍是旧的"。
 */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { fetchProfile, listRevisions, saveProfileBasics, type Profile } from '@/shared/api/profile'

import ProfileView from './ProfileView.vue'

// 只替换本页真正调用的接口；其余导出（描述符需要的写法集合）保持真实，避免测试用的替身与
// 真实类型脱节。
vi.mock('@/shared/api/profile', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/profile')>()
  return {
    ...actual,
    fetchProfile: vi.fn(),
    saveProfileBasics: vi.fn(),
    createProfile: vi.fn(),
    createRevision: vi.fn(),
    savePreference: vi.fn(),
    listRevisions: vi.fn(),
  }
})

function profileFixture(): Profile {
  return {
    id: 'profile-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
    singleton_key: 'default',
    full_name: '张伟',
    headline: '后端工程师',
    summary: null,
    email: null,
    phone: null,
    city: '上海',
    links: [],
    evidences: [],
    skills: [],
    experiences: [],
    projects: [],
    educations: [],
    languages: [],
    preference: null,
  }
}

function mountView(): VueWrapper {
  return mount(ProfileView)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchProfile).mockResolvedValue(profileFixture())
  vi.mocked(saveProfileBasics).mockResolvedValue(profileFixture())
  vi.mocked(listRevisions).mockResolvedValue([])
})

enableAutoUnmount(afterEach)

describe('ProfileView', () => {
  it('档案尚未创建时进入创建引导，而不是显示加载失败', async () => {
    vi.mocked(fetchProfile).mockRejectedValueOnce(
      new ApiError({ code: 'RESOURCE_NOT_FOUND', message: '个人档案尚未创建。', status: 404 }),
    )

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('创建个人档案')
    expect(wrapper.find('[data-testid="profile-import-panel"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('创建后即可单独维护工作经历和教育经历')
    expect(wrapper.find('[data-testid="load-error"]').exists()).toBe(false)
    // 未创建时不应渲染依赖档案存在与否的面板。
    expect(wrapper.find('[data-testid="panel-skills"]').exists()).toBe(false)
  })

  it('加载失败时显示后端提示与错误编号，不显示业务面板', async () => {
    vi.mocked(fetchProfile).mockRejectedValueOnce(
      new ApiError({
        code: 'NETWORK_ERROR',
        message: '无法连接到服务，请确认后端是否已启动。',
        requestId: 'req-network',
      }),
    )

    const wrapper = mountView()
    await flushPromises()

    const alert = wrapper.find('[data-testid="load-error"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('无法连接到服务，请确认后端是否已启动。')
    expect(alert.text()).toContain('req-network')
    expect(wrapper.find('[data-testid="panel-evidences"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="profile-import-panel"]').exists()).toBe(false)
  })

  it('加载成功后显示全部面板，并把档案内容回填到表单', async () => {
    const wrapper = mountView()
    await flushPromises()

    // 姓名以输入框的值呈现，不在文本节点里，因此断言元素值而不是页面文本。
    const fullName = wrapper.find('[data-testid="panel-basics"] input')
    expect((fullName.element as HTMLInputElement).value).toBe('张伟')
    expect(wrapper.find('[data-testid="profile-import-panel"]').exists()).toBe(true)
    for (const key of [
      'basics',
      'preference',
      'evidences',
      'skills',
      'experiences',
      'projects',
      'educations',
      'languages',
      'revisions',
    ]) {
      expect(wrapper.find(`[data-testid="panel-${key}"]`).exists()).toBe(true)
    }
  })

  it('版本过期时提示冲突并重新加载聚合，使用户能基于最新数据重试', async () => {
    vi.mocked(saveProfileBasics).mockRejectedValueOnce(
      new ApiError({
        code: 'CONFLICT',
        message: '记录已被更新，请刷新后重试。',
        status: 409,
        details: [{ field: 'version', reason: '当前版本为 2，提交的是 1。' }],
      }),
    )
    const wrapper = mountView()
    await flushPromises()
    expect(fetchProfile).toHaveBeenCalledTimes(1)

    await wrapper.find('[data-testid="save-basics"]').trigger('click')
    await flushPromises()

    expect(saveProfileBasics).toHaveBeenCalledTimes(1)
    const banner = wrapper.find('[data-testid="conflict-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('记录已被更新，请刷新后重试。')
    // 关键断言：提示之外还必须重新加载，否则用户重试时提交的仍是旧版本号。
    expect(fetchProfile).toHaveBeenCalledTimes(2)
  })
})
