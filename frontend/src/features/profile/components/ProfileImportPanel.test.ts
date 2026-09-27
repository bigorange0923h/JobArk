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

import { IMPORT_BASIC_FIELDS } from '../basicsFields'
import ProfileImportPanel from './ProfileImportPanel.vue'

vi.mock('@/shared/api/profile', () => ({
  previewProfileImportStream: vi.fn(),
  confirmProfileImport: vi.fn(),
}))

const candidate: ProfileImportPreview = {
  filename: 'sample.html',
  source_hash: 'a'.repeat(64),
  candidate: {
    full_name: '张三', name_quote: '张三', headline: null, summary: null,
    email: null, phone: null, city: null, links: [],
    skills: [{ origin: 'RESUME', name: 'Python', source_quote: '熟悉 Python' }],
    experiences: [], projects: [], educations: [],
  },
  completeness: { status: 'COMPLETE', valid_item_count: 1, rejected_item_count: 0, unmapped_field_count: 0, excluded_field_count: 0 },
  rejected_items: [],
  warnings: [],
  fixture: false,
}

/** 带两条技能的预览：技能卡相关用例共用，避免每个用例各写一份候选。 */
function skillPreview(): ProfileImportPreview {
  return {
    ...candidate,
    candidate: {
      ...candidate.candidate,
      skills: [
        { origin: 'RESUME', name: 'Python', source_quote: '熟悉 Python' },
        { origin: 'RESUME', name: 'PostgreSQL', source_quote: '与 PostgreSQL' },
      ],
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(previewProfileImportStream).mockResolvedValue(candidate)
  vi.mocked(confirmProfileImport).mockResolvedValue({
    profile_id: 'id', created_profile: true, skills_added: 1, experiences_added: 0, projects_added: 0,
    educations_added: 0, manual_item_count: 0,
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
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(false)
  })
}

/**
 * 走完写入前的二次确认：点「确认」按钮，再在弹窗里确认一次。
 *
 * 两步刻意分开：按钮只表达"我要写入"的意图，真正写库的是弹窗里那一下。
 */
async function confirmFromDialog(wrapper: VueWrapper): Promise<void> {
  await wrapper.find('[data-testid="confirm-import"]').trigger('click')
  await wrapper.find('[data-testid="confirm-import-dialog-ok"]').trigger('click')
  await flushPromises()
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
  // 外发提示改为醒目小字 + 主动点「继续」：弹窗里不再有勾选框。
  const notice = modal.find('[data-testid="profile-import-send-notice"]')
  expect(notice.exists()).toBe(true)
  expect(notice.classes()).toContain('import-send-notice')
  expect(notice.text()).toContain('点击「继续」')
  expect(notice.text()).toContain('大模型服务')
  expect(notice.text()).toContain('最多会自动重试一次')
  expect(modal.find('input[type="checkbox"]').exists()).toBe(false)
  // 未选文件时"继续"不可用，因此此刻不可能存在任何外发请求。
  expect(wrapper.find('[data-testid="preview-import"]').attributes('disabled')).toBeDefined()

  await selectFile(wrapper)
  expect(wrapper.text()).toContain('sample.html')
  expect(previewProfileImportStream).not.toHaveBeenCalled()
  // 选了文件即可继续：点「继续」本身即为同意。
  expect(wrapper.find('[data-testid="preview-import"]').attributes('disabled')).toBeUndefined()
  await wrapper.find('[data-testid="preview-import"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(false)
  })

  expect(previewProfileImportStream).toHaveBeenCalledOnce()
  // 预览成功后弹窗关闭，候选在面板里核对。
  expect(wrapper.find('[data-testid="import-modal"]').exists()).toBe(false)
  expect(wrapper.text()).toContain('姓名原文：张三')
  // 有候选即可点「确认」：它只打开二次确认弹窗，本身不写库。
  expect(wrapper.find('[data-testid="confirm-import"]').attributes('disabled')).toBeUndefined()
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

it('写入必须经过二次确认弹窗：按钮只打开弹窗，弹窗里确认才落库', async () => {
  const onChanged = vi.fn()
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false }, attrs: { onChanged } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  expect(wrapper.find('[data-testid="confirm-import"]').text()).toContain('确认使用候选并创建个人档案')
  expect(wrapper.find('[data-testid="import-back-to-manual"]').exists()).toBe(true)
  // 常驻勾选框已移除：确认一律在弹窗里重新询问，不存在"勾过一次就一直有效"。
  expect(wrapper.find('[data-testid="profile-import-reviewed"]').exists()).toBe(false)
  expect(wrapper.find('[data-testid="confirm-import-dialog"]').exists()).toBe(false)
  expect(confirmProfileImport).not.toHaveBeenCalled()

  await wrapper.find('[data-testid="confirm-import"]').trigger('click')
  const dialog = wrapper.find('[data-testid="confirm-import-dialog"]')
  expect(dialog.exists()).toBe(true)
  // 弹窗保留需求规定的那句确认文案，且不写成"已证明全部验证"。
  expect(dialog.text()).toContain('我已核对，这些内容可以加入个人档案并用于匹配和简历候选')
  expect(dialog.text()).toContain('不代表已独立核实')
  expect(dialog.find('input[type="checkbox"]').exists()).toBe(false)
  // 弹窗只是询问：这一步还不能写。
  expect(confirmProfileImport).not.toHaveBeenCalled()

  await wrapper.find('[data-testid="confirm-import-dialog-ok"]').trigger('click')
  await flushPromises()

  expect(confirmProfileImport).toHaveBeenCalledOnce()
  expect(onChanged).toHaveBeenCalledTimes(1)
})

it('取消二次确认不写入，且下次仍会重新询问', async () => {
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  await wrapper.find('[data-testid="confirm-import"]').trigger('click')
  await wrapper.find('[data-testid="confirm-import-dialog-cancel"]').trigger('click')
  expect(wrapper.find('[data-testid="confirm-import-dialog"]').exists()).toBe(false)
  expect(confirmProfileImport).not.toHaveBeenCalled()

  // 取消后再改一条候选重新确认：仍然要重新询问一遍，取消了不等于"已确认"。
  await wrapper.find('[data-testid="candidate-basics-full_name"]').setValue('张三（改）')
  await wrapper.find('[data-testid="confirm-import"]').trigger('click')
  expect(wrapper.find('[data-testid="confirm-import-dialog"]').exists()).toBe(true)
  expect(confirmProfileImport).not.toHaveBeenCalled()
})

it('候选按卡片渲染项目经历，可修正字段并提交修正后的内容与项目选择', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue({
    ...candidate,
    candidate: {
      ...candidate.candidate,
      projects: [
        {
          origin: 'RESUME', name: '订单系统重构', role: '项目经理', description: null, responsibilities: null,
          achievements: null, tech_stack: [], url: null, start_date: null, end_date: null,
          source_quote: '订单系统重构',
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
  await wrapper.find('[data-testid="skill-name-0"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="skill-name-input-0"]').exists()).toBe(true)
  })
  await wrapper.find('[data-testid="skill-name-input-0"]').setValue('Python 3')
  await wrapper.find('[data-testid="skill-name-input-0"]').trigger('blur')
  await wrapper.find('[data-testid="candidate-item-projects-0"] input.ant-input').setValue('订单系统重构（自研）')

  // 改到摘录之外后，界面上当场把来源标成「本人填写」，并保留原文摘录供对照（不再作为来源）。
  expect(wrapper.find('[data-testid="origin-projects-0"]').text()).toContain('本人填写')
  expect(wrapper.find('[data-testid="quote-projects-0"]').text()).toContain('订单系统重构')

  await confirmFromDialog(wrapper)

  expect(confirmProfileImport).toHaveBeenCalledOnce()
  const payload = vi.mocked(confirmProfileImport).mock.calls[0][0]
  expect(payload.candidate.skills[0].name).toBe('Python 3')
  expect(payload.candidate.projects[0].name).toBe('订单系统重构（自研）')
  expect(payload.projectIndices).toEqual([0])
  // 改到摘录之外的内容不再挂旧摘录：按「本人填写」提交，也不要求用户补一段摘录。
  expect(payload.candidate.projects[0].origin).toBe('MANUAL')
  expect(payload.candidate.projects[0].source_quote).toBeNull()
  expect(payload.candidate.skills[0].origin).toBe('MANUAL')
})

it('候选可补全个人简介与公开链接，确认时随候选提交，留空行不产生空链接', async () => {
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  // 与“创建个人档案”共用同一个表单：个人简介与公开链接在候选页同样可编辑。
  await wrapper.find('[data-testid="candidate-basics-summary"]').setValue('五年后端经验')
  await wrapper.find('[data-testid="add-link"]').trigger('click')
  await wrapper.find('[data-testid="link-label-0"]').setValue('GitHub')
  await wrapper.find('[data-testid="link-url-0"]').setValue('https://github.com/zhangsan')
  // 再点一次会新增一行整行留空的链接：它不参与提交，也不会变成一条空链接事实。
  await wrapper.find('[data-testid="add-link"]').trigger('click')

  await confirmFromDialog(wrapper)

  expect(confirmProfileImport).toHaveBeenCalledOnce()
  const payload = vi.mocked(confirmProfileImport).mock.calls[0][0]
  expect(payload.candidate.summary).toBe('五年后端经验')
  expect(payload.candidate.links).toEqual([{ label: 'GitHub', url: 'https://github.com/zhangsan' }])
})

it('链接只填一半时拦下确认并就地提示，不发起请求', async () => {
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  await wrapper.find('[data-testid="add-link"]').trigger('click')
  await wrapper.find('[data-testid="link-label-0"]').setValue('GitHub')
  await confirmFromDialog(wrapper)

  expect(confirmProfileImport).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('每条链接都需要同时填写名称与地址')
})

it('已有档案时个人简介与公开链接只读，并说明导入不覆盖它们', async () => {
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: true } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  expect(wrapper.find('[data-testid="candidate-basics-summary"]').attributes('disabled')).toBeDefined()
  expect(wrapper.find('[data-testid="add-link"]').attributes('disabled')).toBeDefined()
  // 禁用必须配一句解释，否则用户只会觉得“这里填不了”。
  expect(wrapper.text()).toContain('个人简介与公开链接不会被导入')
})

it('候选页可新增各类条目，新增条目按「本人填写」提交且不需要摘录', async () => {
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  // 技能：点击「新增技能」后直接改名（技能卡点击即编辑）。
  await wrapper.find('[data-testid="add-item-skills"]').trigger('click')
  await wrapper.find('[data-testid="skill-name-1"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="skill-name-input-1"]').exists()).toBe(true)
  })
  await wrapper.find('[data-testid="skill-name-input-1"]').setValue('Kubernetes')
  await wrapper.find('[data-testid="skill-name-input-1"]').trigger('blur')

  // 项目：新增卡片后填名称（其余字段留空，本来就没有可填的内容）。
  await wrapper.find('[data-testid="add-item-projects"]').trigger('click')
  await wrapper.find('[data-testid="candidate-item-projects-0"] input.ant-input').setValue('个人博客系统')

  // 界面上如实标注来源：本人填写，不需要编造原文摘录。
  expect(wrapper.find('[data-testid="origin-skills-1"]').text()).toContain('本人填写')
  expect(wrapper.find('[data-testid="origin-projects-0"]').text()).toContain('本人填写')
  expect(wrapper.find('[data-testid="quote-projects-0"]').text()).toContain('无原文摘录')

  await confirmFromDialog(wrapper)

  const payload = vi.mocked(confirmProfileImport).mock.calls[0][0]
  // 新增条目默认勾选：用户点了新增就是想让它进档案。
  expect(payload.skillIndices).toEqual([0, 1])
  expect(payload.projectIndices).toEqual([0])
  const addedSkill = payload.candidate.skills[1]
  expect(addedSkill.name).toBe('Kubernetes')
  expect(addedSkill.origin).toBe('MANUAL')
  expect(addedSkill.source_quote).toBeNull()
  const addedProject = payload.candidate.projects[0]
  expect(addedProject.name).toBe('个人博客系统')
  expect(addedProject.origin).toBe('MANUAL')
  expect(addedProject.source_quote).toBeNull()
})

it('新增条目缺少必填字段时本地拦下并指出具体条目', async () => {
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  await wrapper.find('[data-testid="add-item-experiences"]').trigger('click')
  await confirmFromDialog(wrapper)

  expect(confirmProfileImport).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('工作经历第 1 条缺少必填的「公司」')
})

it('删除候选项后重建提交下标，避免把剩下的条目错位提交', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue({
    ...candidate,
    candidate: {
      ...candidate.candidate,
      projects: [
        {
          origin: 'MANUAL', name: '要删掉的项目', role: null, description: null, responsibilities: null,
          achievements: null, tech_stack: [], url: null, start_date: null, end_date: null, source_quote: null,
        },
        {
          origin: 'RESUME', name: '订单系统重构', role: null, description: null, responsibilities: null,
          achievements: null, tech_stack: [], url: null, start_date: null, end_date: null,
          source_quote: '订单系统重构',
        },
      ],
    },
  })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper, '<html>张三 熟悉 Python 订单系统重构</html>')

  await wrapper.find('[data-testid="remove-item-projects-0"]').trigger('click')
  await confirmFromDialog(wrapper)

  const payload = vi.mocked(confirmProfileImport).mock.calls[0][0]
  expect(payload.projectIndices).toEqual([0])
  expect(payload.candidate.projects.map((item) => item.name)).toEqual(['订单系统重构'])
})

it('技能卡只保留名称、原文出处与删除，并按网格一行多条排列', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue(skillPreview())
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  // 紧凑网格：多条技能放在同一容器里，而不是每条独占一整行。
  expect(wrapper.find('.skill-grid').exists()).toBe(true)
  expect(wrapper.findAll('.skill-card')).toHaveLength(2)
  const card = wrapper.find('[data-testid="candidate-item-skills-0"]')
  // 不再有"技能名称"字段标签，也没有勾选框：只保留名称、出处与删除。
  expect(card.find('.ant-form-item-label').exists()).toBe(false)
  expect(card.find('input[type="checkbox"]').exists()).toBe(false)
  expect(wrapper.find('[data-testid="skill-name-0"]').text()).toBe('Python')
  expect(wrapper.find('[data-testid="skill-quote-0"]').text()).toContain('熟悉 Python')
  // 删除是图标按钮：不带文字，但必须保留可访问名称。
  const removeButton = wrapper.find('[data-testid="remove-skill-0"]')
  expect(removeButton.exists()).toBe(true)
  expect(removeButton.text()).toBe('')
  expect(removeButton.attributes('aria-label')).toBe('删除该技能')
})

it('点击技能名进入编辑态，回车与失焦都算编辑完成', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue(skillPreview())
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  // 点击名称进入编辑态：出现输入框而不是常驻表单字段。
  await wrapper.find('[data-testid="skill-name-0"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="skill-name-input-0"]').exists()).toBe(true)
  })
  await wrapper.find('[data-testid="skill-name-input-0"]').setValue('Python 3')
  await wrapper.find('[data-testid="skill-name-input-0"]').trigger('keydown', { key: 'Enter' })
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="skill-name-input-0"]').exists()).toBe(false)
  })
  expect(wrapper.find('[data-testid="skill-name-0"]').text()).toBe('Python 3')

  // 失焦同样算编辑完成。
  await wrapper.find('[data-testid="skill-name-1"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="skill-name-input-1"]').exists()).toBe(true)
  })
  await wrapper.find('[data-testid="skill-name-input-1"]').setValue('PostgreSQL 16')
  await wrapper.find('[data-testid="skill-name-input-1"]').trigger('blur')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="skill-name-input-1"]').exists()).toBe(false)
  })
  expect(wrapper.find('[data-testid="skill-name-1"]').text()).toBe('PostgreSQL 16')
})

it('删除技能会从候选中移除该条并重建提交下标', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue(skillPreview())
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  await wrapper.find('[data-testid="remove-skill-0"]').trigger('click')
  await flushPromises()

  expect(wrapper.findAll('.skill-card')).toHaveLength(1)
  expect(wrapper.find('[data-testid="skill-name-0"]').text()).toBe('PostgreSQL')

  await confirmFromDialog(wrapper)

  // 下标是提交契约：删除后必须重建，否则会把剩下的技能错位提交。
  const payload = vi.mocked(confirmProfileImport).mock.calls[0][0]
  expect(payload.candidate.skills.map((skill) => skill.name)).toEqual(['PostgreSQL'])
  expect(payload.skillIndices).toEqual([0])
})

it('夹具模式下展示内置模拟数据警示', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue({ ...skillPreview(), fixture: true })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  const notice = wrapper.find('[data-testid="profile-import-fixture-notice"]')
  expect(notice.exists()).toBe(true)
  expect(notice.text()).toContain('内置模拟数据')
})

it('候选基本信息复用创建档案的字段顺序与标签，长文本字段独占一行', async () => {
  vi.mocked(previewProfileImportStream).mockResolvedValue({
    ...candidate,
    candidate: {
      ...candidate.candidate,
      projects: [
        {
          origin: 'RESUME', name: '订单系统重构', role: '项目经理', description: '主导订单链路拆分',
          responsibilities: null, achievements: null, tech_stack: ['Spring Boot'], url: null,
          start_date: null, end_date: null, source_quote: '订单系统重构',
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
  // 期望值直接来自共享字段定义（末尾是数组字段“公开链接”）：在这里重抄一份标签表，
  // 就又会变成两个各自演化的列表，正是这条用例要防的事。
  expect(labels).toEqual([...IMPORT_BASIC_FIELDS.map((field) => field.label), '公开链接'])

  // 长文本字段（项目说明）独占一行，不跟普通字段挤在同一行。
  const wideItem = wrapper.find('[data-testid="candidate-item-projects-0"] .profile-field-grid__wide')
  expect(wideItem.exists()).toBe(true)
  expect(wideItem.find('textarea.ant-input').exists()).toBe(true)
})

it('勾选的条目缺少必填字段时本地拦截，不发确认请求', async () => {
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  // 把技能名清空：候选允许留空显示，但提交时必须先补齐或删除该条。
  await wrapper.find('[data-testid="skill-name-0"]').trigger('click')
  await vi.waitFor(() => {
    expect(wrapper.find('[data-testid="skill-name-input-0"]').exists()).toBe(true)
  })
  await wrapper.find('[data-testid="skill-name-input-0"]').setValue('')
  await wrapper.find('[data-testid="skill-name-input-0"]').trigger('blur')
  await confirmFromDialog(wrapper)

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
    warnings: [
      {
        group: 'projects', index: 0, code: 'UNMAPPED_MODEL_FIELD', fields: ['deliverables'],
        message: '模型返回了当前档案结构未支持的字段；这些字段未作为候选事实导入。',
      },
      {
        group: 'basics', index: 0, code: 'FIELD_NOT_IN_QUOTE', fields: ['summary', 'links'],
        message: '这些基本信息未能在简历原文中逐字定位或格式不可用，未作为简历事实导入；可由本人补充。',
      },
    ],
  })
  const wrapper = mount(ProfileImportPanel, { props: { hasProfile: false } })
  await wrapper.find('[data-testid="open-import-modal"]').trigger('click')
  await previewFromModal(wrapper)

  const warning = wrapper.find('[data-testid="profile-import-partial-warning"]')
  expect(warning.exists()).toBe(true)
  expect(warning.text()).toContain('本次仅生成部分可验证候选')
  // 分组与字段名按用户语言呈现，而不是把后端键名（experiences、summary）直接摊在界面上。
  expect(warning.text()).toContain('工作经历 第 1 条')
  expect(warning.text()).toContain('未作为候选事实导入')
  expect(warning.text()).toContain('基本信息 第 1 条（个人简介、公开链接）')
  expect(warning.text()).not.toContain('experiences 第')
  expect(warning.text()).not.toContain('summary')
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
