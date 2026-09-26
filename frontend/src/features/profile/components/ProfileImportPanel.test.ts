/** @vitest-environment jsdom */
/**
 * 简历导入必须经过"打开弹窗 → 明确外发同意 → 生成候选 → 人工核对 → 确认写入"这几步。
 *
 * 重点断言两件事：未同意不得调用预览接口；候选卡片可修正、摘录只读，并且确认时提交的是
 * 修正后的内容与勾选的条目下标。
 */
import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { confirmProfileImport, previewProfileImportStream, type ProfileImportPreview } from '@/shared/api/profile'

import ProfileImportPanel from './ProfileImportPanel.vue'

vi.mock('@/shared/api/profile', () => ({
  previewProfileImportStream: vi.fn(),
  confirmProfileImport: vi.fn(),
}))

const candidate: ProfileImportPreview = {
  filename: 'sample.html',
  source_hash: 'a'.repeat(64),
  candidate: {
    full_name: '张三', name_quote: '张三', headline: null, email: null, phone: null, city: null,
    skills: [{ name: 'Python', source_quote: '熟悉 Python' }],
    experiences: [], projects: [], educations: [],
  },
  completeness: { status: 'COMPLETE', valid_item_count: 1, rejected_item_count: 0, unmapped_field_count: 0, excluded_field_count: 0 },
  rejected_items: [],
  warnings: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(previewProfileImportStream).mockResolvedValue(candidate)
  vi.mocked(confirmProfileImport).mockResolvedValue({
    profile_id: 'id', created_profile: true, skills_added: 1, experiences_added: 0, projects_added: 0, educations_added: 0,
  })
})

enableAutoUnmount(afterEach)

/** 在弹窗里选择一个文件。 */
async function selectFile(wrapper: VueWrapper, name = 'sample.html', body = '<html><body>张三 熟悉 Python</body></html>'): Promise<void> {
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: [new File([body], name, { type: 'text/html' })],
  })
  await input.trigger('change')
}

/**
 * 走完弹窗：选文件、勾选同意、点击继续，并等待预览结果。
 *
 * 用 `vi.waitFor` 等条件而不是固定延时：文件读取（FileReader）与请求都走异步链，
 * 并行跑整套测试时会更慢，固定延时会让用例偶发失败在与被测逻辑无关的地方。
 */
async function previewFromModal(wrapper: VueWrapper, body?: string): Promise<void> {
  await selectFile(wrapper, 'sample.html', body)
  await wrapper.find('[data-testid="profile-import-consent"]').setValue(true)
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(false)
  })
}

it('初始只展示入口按钮，弹窗先告知外发范围；未同意不得调用预览接口', async () => {
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  // 初始不堆叠文件选择与确认控件。
  expect(wrapper.find('[data-testid="profile-import-panel"]').exists()).toBe(true)
  expect(wrapper.find('input[type="file"]').exists()).toBe(false)
  expect(wrapper.text()).toContain('大模型服务')

  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  const modal = wrapper.find('[data-testid="import-modal"]')
  expect(modal.exists()).toBe(true)
  expect(modal.text()).toContain('大模型服务')
  expect(modal.text()).toContain('不会自动写入个人档案')
  // 未选文件、未勾选同意时"继续"不可用。
  expect(wrapper.find('[data-testid="preview-import"]').attributes('disabled')).toBeDefined()

  await selectFile(wrapper)
  expect(wrapper.text()).toContain('sample.html')
  expect(wrapper.find('[data-testid="preview-import"]').attributes('disabled')).toBeDefined()
  expect(previewProfileImportStream).not.toHaveBeenCalled()

  await wrapper.find('[data-testid="profile-import-consent"]').setValue(true)
  expect(wrapper.find('[data-testid="preview-import"]').attributes('disabled')).toBeUndefined()
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(false)
  })

  expect(previewProfileImportStream).toHaveBeenCalledOnce()
  // 预览成功后弹窗关闭，候选在面板里核对。
  expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(false)
  expect(wrapper.text()).toContain('姓名原文：张三')
  expect(wrapper.find('[data-testid="confirm-import"]').attributes('disabled')).toBeDefined()
  expect(confirmProfileImport).not.toHaveBeenCalled()
})

it('被页面按钮驱动时不重复提供入口按钮，只展示候选区', () => {
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false, showEntry: false } })

  // 页面已有同名按钮：展开区里不能再出现第二个入口（否则用户会以为点错了地方）。
  expect(wrapper.find('[data-testid="open-import-modal"]').exists()).toBe(false)
  expect(wrapper.find('.import-entry').exists()).toBe(false)
  // 还没有候选时给出下一步提示，而不是留一片空白。
  expect(wrapper.text()).toContain('还没有待核对候选')
})

it('未核对不得确认；确认按钮在无档案时明确为"确认使用候选并创建个人档案"', async () => {
  const onChanged = vi.fn()
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false }, attrs: { onChanged } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  expect(wrapper.find('[data-testid="confirm-import"]').text()).toContain('确认使用候选并创建个人档案')
  expect(wrapper.find('[data-testid="import-back-to-manual"]').exists()).toBe(true)
  expect(confirmProfileImport).not.toHaveBeenCalled()

  await wrapper.find('[data-testid="profile-import-reviewed"]').setValue(true)
  await wrapper.find('[data-testid="confirm-import"]').trigger('click')
  await flushPromises()

  expect(confirmProfileImport).toHaveBeenCalledOnce()
  expect(onChanged).toHaveBeenCalledTimes(1)
})

it('候选按卡片渲染项目经历，可修正字段并提交修正后的内容与项目选择', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue({
    ...candidate,
    candidate: {
      ...candidate.candidate,
      projects: [
        {
          name: '订单系统重构', role: '项目经理', description: null, responsibilities: null, achievements: null,
          tech_stack: [], url: null, start_date: null, end_date: null, source_quote: '订单系统重构',
        },
      ],
    },
  })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper, '<html>张三 熟悉 Python 订单系统重构</html>')

  // 项目经历区块按候选渲染成卡片；技能与项目名都可以在预览里改。
  // 选择器限定为文本输入（`input.ant-input`）：条目内还有复选框的 input 与 textarea，取第一个会命错元素。
  expect(wrapper.text()).toContain('项目经历（1）')
  await wrapper.find('[data-testid="candidate-item-skills-0"] input.ant-input').setValue('Python 3')
  await wrapper.find('[data-testid="candidate-item-projects-0"] input.ant-input').setValue('订单系统重构（自研）')
  await wrapper.find('[data-testid="profile-import-reviewed"]').setValue(true)
  await wrapper.find('[data-testid="confirm-import"]').trigger('click')
  await flushPromises()

  expect(confirmProfileImport).toHaveBeenCalledOnce()
  const payload = vi.mocked(confirmProfileImport).mock.calls[0][0]
  expect(payload.candidate.skills[0].name).toBe('Python 3')
  expect(payload.candidate.projects[0].name).toBe('订单系统重构（自研）')
  expect(payload.projectIndices).toEqual([0])
  // 摘录保持只读：它是来源凭证，不能被编辑成别的内容。
  expect(payload.candidate.projects[0].source_quote).toBe('订单系统重构')
})

it('候选基本信息复用创建档案的字段顺序与标签，长文本字段独占一行', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue({
    ...candidate,
    candidate: {
      ...candidate.candidate,
      projects: [
        {
          name: '订单系统重构', role: '项目经理', description: '主导订单链路拆分', responsibilities: null,
          achievements: null, tech_stack: ['Spring Boot'], url: null, start_date: null, end_date: null,
          source_quote: '订单系统重构',
        },
      ],
    },
  })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  // 基本信息用共享字段定义与共享网格渲染：顺序与标签必须与创建档案页一致。
  const basics = wrapper.find('[data-testid="profile-import-preview"] .profile-field-grid')
  expect(basics.classes()).toContain('profile-field-grid')
  const labels = basics.findAll('.ant-form-item-label label').map((node) => node.text())
  expect(labels).toEqual(['姓名', '一句话头衔', '邮箱', '手机', '所在城市'])

  // 长文本字段（项目说明）独占一行，不跟普通字段挤在同一行。
  const wideItem = wrapper.find('[data-testid="candidate-item-projects-0"] .profile-field-grid__wide')
  expect(wideItem.exists()).toBe(true)
  expect(wideItem.find('textarea.ant-input').exists()).toBe(true)
})

it('勾选的条目缺少必填字段时本地拦截，不发确认请求', async () => {
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  // 把技能名清空：候选允许留空显示，但勾选提交时必须先补齐。
  await wrapper.find('[data-testid="candidate-item-skills-0"] input.ant-input').setValue('')
  await wrapper.find('[data-testid="profile-import-reviewed"]').setValue(true)
  await wrapper.find('[data-testid="confirm-import"]').trigger('click')
  await flushPromises()

  expect(confirmProfileImport).not.toHaveBeenCalled()
  expect(wrapper.find('[data-testid="profile-import-error"]').text()).toContain('技能名称')
})

it('返回手动创建时只发出返回事件，不调用确认接口', async () => {
  const onBack = vi.fn()
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false }, attrs: { onBack } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  await wrapper.find('[data-testid="import-back-to-manual"]').trigger('click')

  expect(onBack).toHaveBeenCalledTimes(1)
  expect(confirmProfileImport).not.toHaveBeenCalled()
  // 返回后候选仍在内存里，便于再次进入核对。
  expect(wrapper.find('[data-testid="profile-import-preview"]').exists()).toBe(true)
})

it('部分候选会明确展示遗漏条目和未映射字段', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue({
    ...candidate,
    completeness: { status: 'PARTIAL', valid_item_count: 1, rejected_item_count: 1, unmapped_field_count: 1, excluded_field_count: 0 },
    rejected_items: [{
      group: 'experiences', index: 0, code: 'EVIDENCE_INVALID', fields: [],
      message: '该条目的字段或摘录无法逐字定位到简历原文，未进入待确认列表。',
    }],
    warnings: [{
      group: 'projects', index: 0, code: 'UNMAPPED_MODEL_FIELD', fields: ['deliverables'],
      message: '模型返回了当前档案结构未支持的字段；这些字段未作为候选事实导入。',
    }],
  })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  const warning = wrapper.find('[data-testid="profile-import-partial-warning"]')
  expect(warning.exists()).toBe(true)
  expect(warning.text()).toContain('本次仅生成部分可验证候选')
  expect(warning.text()).toContain('experiences 第 1 条')
  expect(warning.text()).toContain('deliverables')
  expect(warning.text()).toContain('未作为候选事实导入')
})

it('用户确认上传后按真实字节显示上传进度，上传完成再显示后端阶段', async () => {
  let finish: ((value: ProfileImportPreview) => void) | undefined
  vi.mocked(previewProfileImportStream).mockImplementation(async (_filename, _content, _consent, handlers) => {
    handlers.onUploadProgress?.(30, 120)
    return new Promise<ProfileImportPreview>((resolve) => { finish = resolve })
  })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await selectFile(wrapper)
  await wrapper.find('[data-testid="profile-import-consent"]').setValue(true)
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="profile-import-upload-progress"]').exists()).toBe(true)
  })

  // 上传阶段显示真实百分比（30/120 → 25%），而不是把模型阶段伪装成进度。
  const upload = wrapper.find('[data-testid="profile-import-upload-progress"]')
  expect(upload.text()).toContain('正在上传简历文件')
  expect(upload.text()).toContain('25%')

  finish?.(candidate)
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="profile-import-preview"]').exists()).toBe(true)
  })
  expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(false)
})

it('生成期间展示后端报告的阶段并保持继续按钮忙碌', async () => {
  let finish: ((value: ProfileImportPreview) => void) | undefined
  vi.mocked(previewProfileImportStream).mockImplementation(async (_filename, _content, _consent, handlers) => {
    handlers.onStage('ai_request_started')
    return new Promise<ProfileImportPreview>((resolve) => { finish = resolve })
  })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await selectFile(wrapper)
  await wrapper.find('[data-testid="profile-import-consent"]').setValue(true)
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="profile-import-progress"]').text()).toContain('大模型服务正在生成候选')
  })
  expect(wrapper.find('[data-testid="preview-import"]').attributes('disabled')).toBeDefined()

  finish?.(candidate)
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="profile-import-preview"]').exists()).toBe(true)
  })
  expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(false)
})
