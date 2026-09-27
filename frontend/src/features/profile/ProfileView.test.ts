/**
 * @vitest-environment jsdom
 *
 * 个人资料页的状态与错误处理测试。
 *
 * 覆盖四种页面状态中的三种（加载中由 `a-spin` 呈现，随其他用例一并验证），以及两条最容易出错
 * 的路径：
 * - 乐观锁冲突：唯一必须"重新加载才能继续"的失败，断言提示之外还必须重新拉取聚合，
 *   只断言提示会漏掉"界面提示了但数据仍是旧的"。
 * - 无档案时的创建路径：手动创建与从简历导入必须互斥展示；返回手动创建不落库且保留内存候选；
 *   确认导入后刷新聚合并展示正式档案。
 */

import { enableAutoUnmount, flushPromises, mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import {
  confirmProfileImport,
  createProfile,
  fetchProfile,
  listRevisions,
  previewProfileImportStream,
  saveProfileBasics,
  type Profile,
  type ProfileImportPreview,
} from '@/shared/api/profile'

import ProfileView from './ProfileView.vue'
import { BASIC_FIELDS, IMPORT_BASIC_FIELDS } from './basicsFields'

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
    previewProfileImportStream: vi.fn(),
    confirmProfileImport: vi.fn(),
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

/** 后端在"档案尚未创建"时返回 404；这不是错误，而是一等状态。 */
function profileNotFound(): ApiError {
  return new ApiError({ code: 'RESOURCE_NOT_FOUND', message: '个人档案尚未创建。', status: 404 })
}

/** 一份最小的导入预览，只含一条技能候选。 */
function importPreviewFixture(): ProfileImportPreview {
  return {
    filename: 'sample.html',
    source_hash: 'a'.repeat(64),
    candidate: {
      full_name: '张三',
      name_quote: '张三',
      headline: null,
      summary: null,
      email: null,
      phone: null,
      city: null,
      links: [],
      skills: [{ origin: 'RESUME', name: 'Python', source_quote: '熟悉 Python' }],
      experiences: [],
      projects: [],
      educations: [],
    },
    completeness: {
      status: 'COMPLETE',
      valid_item_count: 1,
      rejected_item_count: 0,
      unmapped_field_count: 0,
      excluded_field_count: 0,
    },
    rejected_items: [],
    warnings: [],
    fixture: false,
  }
}

function mountView(): VueWrapper {
  return mount(ProfileView)
}

/**
 * 走完"选择文件 → 同意外发 → 继续"三步生成候选。
 *
 * 尽量用真实点击而不是 `$emit`：这样验证的是页面与面板之间的实际接线（弹窗、互斥、事件），
 * 而不是测试自己触发的事件。
 */
async function generateImportPreview(wrapper: VueWrapper): Promise<void> {
  // 选择"从已有简历导入"会直接弹出文件选择弹窗；先等一次刷新确保弹窗已挂载。
  await flushPromises()
  expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(true)
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: [new File(['<html>张三 熟悉 Python</html>'], 'sample.html', { type: 'text/html' })],
  })
  await input.trigger('change')
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  // 等候选真的落到面板，而不是赌一个固定延时。
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="profile-import-preview"]').exists()).toBe(true)
  })
}

/** 基本信息字段在页面上的可比较形态；用标签定位，因为两页共用同一套字段定义。 */
interface BasicFieldShape {
  label: string
  control: string
  placeholder: string | null
  maxlength: string | null
  required: boolean
}

/**
 * 读取一个基本信息区块的字段形态。
 *
 * 用于断言“两个页面字段一模一样”：只比标签、控件形态、占位符、长度上限与必填标记——
 * 这些正是共享字段定义（`basicsFields.ts`）负责的内容；字段值不在比较范围内。
 *
 * 没有标签或没有控件的表单项会被跳过：创建页的“公开链接”在尚未添加任何链接时只渲染
 * “添加链接”按钮，那不是一个基本信息字段。
 */
function basicFieldShapes(section: DOMWrapper<Element>): BasicFieldShape[] {
  return section
    .findAll('.ant-form-item')
    .map((item) => {
      const label = item.find('label')
      const control = item.find('input, textarea')
      if (!label.exists() || !control.exists()) return null
      return {
        label: label.text(),
        control: control.element.tagName.toLowerCase(),
        placeholder: control.attributes('placeholder') ?? null,
        maxlength: control.attributes('maxlength') ?? null,
        required: item.find('.ant-form-item-required').exists(),
      }
    })
    .filter((shape): shape is BasicFieldShape => shape !== null)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchProfile).mockResolvedValue(profileFixture())
  vi.mocked(saveProfileBasics).mockResolvedValue(profileFixture())
  vi.mocked(listRevisions).mockResolvedValue([])
  vi.mocked(previewProfileImportStream).mockResolvedValue(importPreviewFixture())
  vi.mocked(confirmProfileImport).mockResolvedValue({
    profile_id: 'profile-1',
    created_profile: true,
    skills_added: 1,
    experiences_added: 0,
    projects_added: 0,
    educations_added: 0,
    manual_item_count: 0,
  })
})

enableAutoUnmount(afterEach)

describe('ProfileView', () => {
  it('未建档时直接显示空的手动表单，导入入口在标题右侧', async () => {
    vi.mocked(fetchProfile).mockRejectedValueOnce(profileNotFound())

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('档案与联系方式')
    expect(wrapper.find('[data-testid="panel-basics"]').isVisible()).toBe(true)
    expect(wrapper.find('[data-testid="start-resume-import"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="load-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="profile-import-preview"]').exists()).toBe(false)
    // 依赖档案存在与否的面板在任何情况下都不出现。
    expect(wrapper.find('[data-testid="panel-skills"]').exists()).toBe(false)
  })

  it('选择"从已有简历导入"在当前页弹出文件选择弹窗，不跳转到单独页面', async () => {
    vi.mocked(fetchProfile).mockRejectedValueOnce(profileNotFound())
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(false)

    await wrapper.find('[data-testid="start-resume-import"]').trigger('click')
    await flushPromises()

    const modal = wrapper.find('[data-testid="import-modal"]')
    expect(modal.exists()).toBe(true)
    // 弹窗里必须能提供简历文件，并在上传前说明数据外发范围。
    expect(modal.find('input[type="file"]').exists()).toBe(true)
    expect(modal.text()).toContain('大模型服务')
    expect(modal.text()).toContain('不会自动写入个人档案')
    // 手动表单不因文件弹窗而卸载；标题右侧是唯一入口。
    expect(wrapper.find('[data-testid="panel-basics"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="open-import-modal"]')).toHaveLength(0)
  })

  it('点击标题右侧导入按钮不切走手动表单', async () => {
    vi.mocked(fetchProfile).mockRejectedValueOnce(profileNotFound())
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="start-resume-import"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="panel-basics"]').isVisible()).toBe(true)
    expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(true)
  })

  it('上传继续后在弹窗内显示填充表单，取消不落库且可恢复草稿', async () => {
    vi.mocked(fetchProfile).mockRejectedValueOnce(profileNotFound())
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="start-resume-import"]').trigger('click')
    await flushPromises()
    await generateImportPreview(wrapper)
    expect(wrapper.find('[data-testid="profile-import-preview"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(false)

    await wrapper.find('[data-testid="cancel-review"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="panel-basics"]').isVisible()).toBe(true)
    expect(wrapper.find('[data-testid="profile-import-preview"]').exists()).toBe(false)
    expect(createProfile).not.toHaveBeenCalled()
    expect(confirmProfileImport).not.toHaveBeenCalled()
    await wrapper.find('[data-testid="start-resume-import"]').trigger('click')
    expect(wrapper.find('[data-testid="profile-import-preview"]').exists()).toBe(true)
  })

  it('确认导入后刷新档案聚合并展示正式档案', async () => {
    vi.mocked(fetchProfile).mockRejectedValueOnce(profileNotFound()).mockResolvedValueOnce(profileFixture())
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="start-resume-import"]').trigger('click')
    await generateImportPreview(wrapper)
    // 核对弹窗里的确认是唯一写入动作。
    await wrapper.find('[data-testid="confirm-import"]').trigger('click')
    await flushPromises()

    expect(confirmProfileImport).toHaveBeenCalledOnce()
    // 关键断言：确认后必须重新拉取聚合，界面才可能显示正式档案。
    expect(fetchProfile).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="profile-import-preview"]').exists()).toBe(false)
    expect((wrapper.find('[data-testid="panel-basics"] input').element as HTMLInputElement).value).toBe('张伟')
  })

  it('候选页与手动创建页用同一套字段与布局，不维护第二份模板', async () => {
    vi.mocked(fetchProfile).mockRejectedValueOnce(profileNotFound())

    const wrapper = mountView()
    await flushPromises()

    // 手动表单一直在页面，导入候选在弹窗中；两侧复用同一字段实现。
    await wrapper.find('[data-testid="start-resume-import"]').trigger('click')
    await generateImportPreview(wrapper)

    // 两侧都由同一个共享布局组件渲染：不是"看起来相似"，而是同一份代码。
    const createSection = wrapper.find('[data-testid="panel-basics"] .basics-section')
    const candidateSection = wrapper.find('[data-testid="profile-import-panel"] .basics-section')
    expect(createSection.exists()).toBe(true)
    expect(candidateSection.exists()).toBe(true)

    const createFields = basicFieldShapes(createSection)
    const candidateFields = basicFieldShapes(candidateSection)

    // 创建页按共享定义全集渲染（公开链接等额外表单项排在字段之后，不参与比较）。
    expect(createFields.slice(0, BASIC_FIELDS.length).map((field) => field.label)).toEqual(
      BASIC_FIELDS.map((field) => field.label),
    )
    // 候选页渲染的是候选契约支持的子集，顺序与创建页一致。
    expect(candidateFields.map((field) => field.label)).toEqual(
      IMPORT_BASIC_FIELDS.map((field) => field.label),
    )

    // 同名字段在两页的标签、控件形态、占位符、长度上限与必填标记必须逐项相同。
    for (const field of candidateFields) {
      expect(createFields.find((item) => item.label === field.label)).toEqual(field)
    }

    // 公开链接是数组字段：两页同样各有同一个链接编辑区，标签与帮助文本逐字一致。
    for (const section of [createSection, candidateSection]) {
      const linksItem = section
        .findAll('.ant-form-item')
        .find((item) => item.find('label').text() === '公开链接')
      expect(linksItem).toBeDefined()
      expect(linksItem?.text()).toContain('例如 GitHub、博客；留空的整行会被忽略。')
    }

    // 布局同源：两页都用同一套字段网格（桌面端每行最多两个普通字段、长文本独占一行、窄屏单列）。
    expect(createSection.find('.profile-field-grid').exists()).toBe(true)
    expect(candidateSection.find('.profile-field-grid').exists()).toBe(true)
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
    // 创建/编辑档案表单与候选核对页共用同一套字段网格（桌面端每行最多两个普通字段）。
    expect(wrapper.find('[data-testid="panel-basics"] .profile-field-grid').exists()).toBe(true)
    expect(wrapper.find('[data-testid="start-resume-import"]').exists()).toBe(true)
    for (const key of ['skills', 'experiences', 'projects', 'educations']) {
      expect(wrapper.find(`[data-testid="form-section-${key}"]`).exists()).toBe(true)
    }
    expect(wrapper.text()).toContain('其他资料与历史记录')
    expect(wrapper.find('[data-testid="panel-preference"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('求职策略')
    expect(wrapper.text()).not.toContain('求职偏好')
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

    // 基本信息改为失焦自动保存：改动后离开输入框即触发 PATCH（不再有保存按钮）。
    const fullName = wrapper.find('[data-testid="panel-basics"] input')
    await fullName.setValue('张伟（改）')
    await fullName.trigger('blur')
    await flushPromises()

    expect(saveProfileBasics).toHaveBeenCalledTimes(1)
    const banner = wrapper.find('[data-testid="conflict-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('记录已被更新，请刷新后重试。')
    // 关键断言：提示之外还必须重新加载，否则用户重试时提交的仍是旧版本号。
    expect(fetchProfile).toHaveBeenCalledTimes(2)
  })
})
