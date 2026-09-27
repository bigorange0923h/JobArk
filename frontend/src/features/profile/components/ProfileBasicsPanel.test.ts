/** @vitest-environment jsdom */
/**
 * 基本信息表单的自动保存机制。
 *
 * 交互约定是"离开输入框即保存"，因此这里逐条固定它最容易出问题的几面：
 * 还在输入时不发请求、没有改动不发请求、必填缺失与半填链接先不保存、
 * 连续保存不误报冲突、保存失败不静默丢弃。
 */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { notification } from 'ant-design-vue'

import { ApiError } from '@/shared/api/client'
import { createProfile, saveProfileBasics, type Profile } from '@/shared/api/profile'

import ProfileBasicsPanel from './ProfileBasicsPanel.vue'
import ProfileCityField from './ProfileCityField.vue'

// 只替换本组件真正调用的写接口；其余导出保持真实，避免替身与真实类型脱节。
vi.mock('@/shared/api/profile', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/profile')>()
  return { ...actual, createProfile: vi.fn(), saveProfileBasics: vi.fn() }
})

function profileFixture(overrides: Partial<Profile> = {}): Profile {
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
    ...overrides,
  }
}

/** 挂载面板；`profile=null` 表示"档案尚未创建"，此时保存动作是 `POST /profile`。 */
function mountPanel(profile: Profile | null, attach = false) {
  const onChanged = vi.fn()
  const onConflict = vi.fn()
  const wrapper: VueWrapper = mount(ProfileBasicsPanel, {
    props: { profile },
    attrs: { onChanged, onConflict },
    ...(attach ? { attachTo: document.body } : {}),
  })
  return { wrapper, onChanged, onConflict }
}

/** 姓名输入框：基本信息区的第一个输入框。 */
function fullName(wrapper: VueWrapper) {
  return wrapper.find('[data-testid="panel-basics"] input')
}

function saveState(wrapper: VueWrapper): string | undefined {
  return wrapper.find('[data-testid="basics-save-status"]').attributes('data-state')
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(createProfile).mockResolvedValue(profileFixture())
  vi.mocked(saveProfileBasics).mockResolvedValue(profileFixture({ version: 2 }))
})

/** 每个用例后卸载组件，避免上一个用例的定时/焦点状态影响下一个。 */
enableAutoUnmount(afterEach)

describe('ProfileBasicsPanel 自动保存', () => {
  it('编辑已有档案：离开输入框才保存，并带上当前版本号', async () => {
    const { wrapper, onChanged } = mountPanel(profileFixture())

    await fullName(wrapper).setValue('张伟（改）')
    // 还在输入中：不发请求，避免每敲一个字都写一次库。
    expect(saveProfileBasics).not.toHaveBeenCalled()

    await fullName(wrapper).trigger('blur')
    await flushPromises()

    expect(saveProfileBasics).toHaveBeenCalledTimes(1)
    expect(vi.mocked(saveProfileBasics).mock.calls[0]?.[0]).toMatchObject({
      version: 1,
      full_name: '张伟（改）',
    })
    expect(onChanged).toHaveBeenCalledTimes(1)
    expect(saveState(wrapper)).toBe('saved')
  })

  it('没有改动时失焦不发请求', async () => {
    const { wrapper } = mountPanel(profileFixture())

    await fullName(wrapper).trigger('blur')
    await flushPromises()

    expect(saveProfileBasics).not.toHaveBeenCalled()
    expect(createProfile).not.toHaveBeenCalled()
    expect(saveState(wrapper)).toBe('saved')
  })

  it('选择省市后按原有自动保存流程提交城市名称', async () => {
    const { wrapper } = mountPanel(profileFixture())
    const city = wrapper.findComponent(ProfileCityField)
    city.findComponent({ name: 'ACascader' }).vm.$emit('change', ['黑龙江省', '哈尔滨市'])
    await flushPromises()

    expect(saveProfileBasics).toHaveBeenCalledTimes(1)
    expect(vi.mocked(saveProfileBasics).mock.calls[0]?.[0]).toMatchObject({ city: '哈尔滨市' })
  })

  it('创建模式：填好姓名后离开输入框即创建，且界面上不再有保存按钮', async () => {
    const { wrapper, onChanged } = mountPanel(null)

    expect(wrapper.find('[data-testid="save-basics"]').exists()).toBe(false)
    expect(saveState(wrapper)).toBe('awaiting-name')

    await fullName(wrapper).setValue('李雷')
    await fullName(wrapper).trigger('blur')
    await flushPromises()

    expect(createProfile).toHaveBeenCalledTimes(1)
    expect(vi.mocked(createProfile).mock.calls[0]?.[0]).toMatchObject({ full_name: '李雷' })
    expect(onChanged).toHaveBeenCalledTimes(1)
  })

  it('姓名为空时先不保存，就地指出必填并保持未保存状态', async () => {
    const warning = vi.spyOn(notification, 'warning').mockImplementation(() => undefined)
    try {
      const { wrapper } = mountPanel(profileFixture(), true)

      await fullName(wrapper).setValue('')
      await fullName(wrapper).trigger('blur')
      await flushPromises()

      expect(saveProfileBasics).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('该项为必填。')
      expect(saveState(wrapper)).toBe('dirty')
      expect(warning).toHaveBeenCalledWith(expect.objectContaining({ class: 'ja-form-notice ja-form-notice--warning' }))
      expect(document.activeElement).toBe(fullName(wrapper).element)
    } finally {
      warning.mockRestore()
    }
  })

  it('链接只填一半先不保存，补齐后再离开输入框才写入', async () => {
    const { wrapper } = mountPanel(profileFixture())

    await wrapper.find('[data-testid="add-link"]').trigger('click')
    await wrapper.find('[data-testid="link-label-0"]').setValue('GitHub')
    await wrapper.find('[data-testid="link-label-0"]').trigger('blur')
    await flushPromises()

    expect(saveProfileBasics).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('每条链接都需要同时填写名称与地址')

    await wrapper.find('[data-testid="link-url-0"]').setValue('https://github.com/zhangwei')
    await wrapper.find('[data-testid="link-url-0"]').trigger('blur')
    await flushPromises()

    expect(saveProfileBasics).toHaveBeenCalledTimes(1)
    expect(vi.mocked(saveProfileBasics).mock.calls[0]?.[0]).toMatchObject({
      links: [{ label: 'GitHub', url: 'https://github.com/zhangwei' }],
    })
  })

  it('删除整行链接是明确动作，立刻保存而不等失焦', async () => {
    const { wrapper } = mountPanel(
      profileFixture({ links: [{ label: 'GitHub', url: 'https://github.com/zhangwei' }] }),
    )

    await wrapper.find('[data-testid="remove-link-0"]').trigger('click')
    await flushPromises()

    expect(saveProfileBasics).toHaveBeenCalledTimes(1)
    expect(vi.mocked(saveProfileBasics).mock.calls[0]?.[0]).toMatchObject({ links: [] })
  })

  it('连续两次保存使用最新版本号，不产生假冲突', async () => {
    vi.mocked(saveProfileBasics)
      .mockResolvedValueOnce(profileFixture({ version: 2 }))
      .mockResolvedValueOnce(profileFixture({ version: 3 }))
    const { wrapper, onConflict } = mountPanel(profileFixture())

    await fullName(wrapper).setValue('张伟 A')
    await fullName(wrapper).trigger('blur')
    await flushPromises()

    // 页面还没重新加载聚合（props.profile.version 仍是 1），用户又改了一次。
    await fullName(wrapper).setValue('张伟 B')
    await fullName(wrapper).trigger('blur')
    await flushPromises()

    expect(saveProfileBasics).toHaveBeenCalledTimes(2)
    expect(vi.mocked(saveProfileBasics).mock.calls[1]?.[0]).toMatchObject({
      version: 2,
      full_name: '张伟 B',
    })
    expect(onConflict).not.toHaveBeenCalled()
  })

  it('保存失败时就地提示字段原因并保持未保存状态', async () => {
    vi.mocked(saveProfileBasics).mockRejectedValueOnce(
      new ApiError({
        code: 'VALIDATION_ERROR',
        message: '请求内容未通过校验。',
        status: 422,
        details: [{ field: 'full_name', reason: '姓名过长。' }],
      }),
    )
    const { wrapper } = mountPanel(profileFixture())

    await fullName(wrapper).setValue('张伟（改）')
    await fullName(wrapper).trigger('blur')
    await flushPromises()

    expect(wrapper.text()).toContain('姓名过长。')
    // 没存上就必须说没存上：不能让用户以为改动已经落库。
    expect(saveState(wrapper)).toBe('dirty')
  })
})
