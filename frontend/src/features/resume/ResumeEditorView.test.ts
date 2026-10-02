/**
 * @vitest-environment jsdom
 *
 * 候选稿编辑器的保存与错误处理测试。
 *
 * 关注三条会直接导致数据问题的路径：
 *
 * - **保存提交的是整份文档与当前版本号**：文档是自包含整体，只提交改动过的字段无法表达"删掉一条"；
 * - **保存成功后要用响应里的新版本号**：否则下一次保存必然因版本过期而失败，用户会以为"改不动"；
 * - **字段级错误要落到具体条目**：后端校验失败时给的是 `skills.0.source_fact_id` 这样的路径，
 *   只弹一句"文档非法"等于让用户自己数第几条出错。
 */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { Select, Upload, notification } from 'ant-design-vue'
import { onBeforeRouteLeave } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { fetchRevision, type Profile } from '@/shared/api/profile'
import { fetchDraft, updateDraft, type ResumeDocument, type ResumeDraft } from '@/shared/api/resume'

import ResumeEditorView from './ResumeEditorView.vue'

/** 拦截全局通知，验证"字段错误留在编辑器、无字段信息的失败才弹通知"。 */
const noticeSpy = vi.spyOn(notification, 'error')

const RESUME_ID = 'resume-1'
const DRAFT_ID = 'draft-1'

const { push } = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('vue-router', () => ({ useRouter: () => ({ push }), onBeforeRouteLeave: vi.fn() }))

vi.mock('@/shared/api/resume', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/resume')>()
  return {
    ...actual,
    fetchDraft: vi.fn(),
    updateDraft: vi.fn(),
  }
})

vi.mock('@/shared/api/profile', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/profile')>()
  return {
    ...actual,
    fetchRevision: vi.fn(),
  }
})

function documentFixture(): ResumeDocument {
  return {
    schema_version: 1,
    basics: { full_name: '张伟', headline: '后端工程师', city: '上海', links: [] },
    contact: { email: 'zhang@example.com', phone: null },
    summary: { text: '5 年后端开发经验。', source_fact_id: null },
    experiences: [
      {
        source_fact_id: null,
        company: '某公司',
        title: '后端工程师',
        location: '上海',
        start_date: '2022-03-01',
        end_date: null,
        highlights: ['负责订单系统重构'],
      },
    ],
    projects: [],
    skills: [{ source_fact_id: 'skill-1', name: 'Python', category: '编程语言', proficiency: 'ADVANCED' }],
    educations: [],
    languages: [],
    section_order: ['SUMMARY', 'EXPERIENCES', 'PROJECTS', 'SKILLS', 'EDUCATIONS', 'LANGUAGES'],
    hidden_sections: [],
  }
}

function draftFixture(overrides: Partial<ResumeDraft> = {}): ResumeDraft {
  return {
    id: DRAFT_ID,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
    version: 1,
    resume_id: RESUME_ID,
    base_resume_version_id: null,
    source_profile_revision_id: 'revision-1',
    document_json: documentFixture(),
    status: 'DRAFT',
    confirmed_resume_version_id: null,
    generator_name: 'manual',
    generator_version: null,
    failure_code: null,
    failure_message: null,
    ...overrides,
  }
}

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
    skills: [
      {
        id: 'skill-1',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        version: 1,
        name: 'Python',
        name_normalized: 'python',
        category: '编程语言',
        proficiency: 'ADVANCED',
        years_of_experience: null,
        source_evidence_id: null,
        claim_status: 'UNVERIFIED',
      },
    ],
    experiences: [],
    projects: [],
    educations: [],
    languages: [],
    preference: null,
  }
}

/** 测试编辑来源固定为修订内容，当前资料不参与下拉。 */
function revisionFixture(profile: Profile): import('@/shared/api/profile').Revision {
  return { id: 'revision-1', profile_id: profile.id, revision_no: 1, created_at: profile.created_at, reason: '生成', snapshot_json: { profile, skills: profile.skills, experiences: profile.experiences, projects: profile.projects, educations: profile.educations, languages: profile.languages } }
}
function mountView(): VueWrapper {
  return mount(ResumeEditorView, { props: { resumeId: RESUME_ID, draftId: DRAFT_ID } })
}

beforeEach(() => {
  vi.clearAllMocks()
  noticeSpy.mockImplementation(() => undefined)
  vi.mocked(fetchDraft).mockResolvedValue(draftFixture())
  vi.mocked(updateDraft).mockImplementation(async (_resumeId, _draftId, payload) => draftFixture({
    version: payload.version + 1,
    document_json: payload.document,
  }))
  vi.mocked(fetchRevision).mockResolvedValue(revisionFixture(profileFixture()))
})

enableAutoUnmount(afterEach)

describe('ResumeEditorView', () => {
  it('加载失败时显示后端提示', async () => {
    vi.mocked(fetchDraft).mockRejectedValueOnce(
      new ApiError({ code: 'RESOURCE_NOT_FOUND', message: '请求的资源不存在。', status: 404 }),
    )

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="load-error"]').text()).toContain('请求的资源不存在。')
    expect(wrapper.find('[data-testid="save-draft"]').exists()).toBe(false)
  })

  it('加载成功后把文档回填到表单', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect((wrapper.find('[data-testid="basics-full-name"]').element as HTMLInputElement).value).toBe('张伟')
    expect((wrapper.find('[data-testid="summary-text"]').element as HTMLTextAreaElement).value).toBe(
      '5 年后端开发经验。',
    )
    expect((wrapper.find('[data-testid="skill-0-name"]').element as HTMLInputElement).value).toBe('Python')
  })

  it('优先从档案选择工作经历并填充内容，手动新增仍不伪造来源', async () => {
    const profile = profileFixture()
    profile.experiences.push({
      id: 'exp-2', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', version: 1,
      company: '新公司', title: '架构师', location: '北京', start_date: '2024-01-01', end_date: null,
      responsibilities: '负责平台架构', achievements: '延迟降低 30%', source_evidence_id: null,
    })
    vi.mocked(fetchRevision).mockResolvedValueOnce(revisionFixture(profile))
    const wrapper = mountView()
    await flushPromises()

    const picker = wrapper.findAllComponents(Select).find((item) => item.attributes('data-testid') === 'source-picker-EXPERIENCES')
    expect(picker?.props('options')).toContainEqual({ value: 'exp-2', label: '新公司 · 架构师' })
    picker?.vm.$emit('change', 'exp-2')
    await wrapper.vm.$nextTick()
    await wrapper.find('[data-testid="add-selected-EXPERIENCES"]').trigger('click')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    const saved = vi.mocked(updateDraft).mock.calls[0]?.[2]?.document
    expect(saved?.experiences[1]).toMatchObject({
      source_fact_id: 'exp-2', company: '新公司', title: '架构师',
      highlights: ['负责平台架构', '延迟降低 30%'],
    })
    expect(picker?.props('options')).not.toContainEqual({ value: 'exp-2', label: '新公司 · 架构师' })

    await wrapper.find('[data-testid="add-experience"]').trigger('click')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(2), { timeout: 1800 })
    expect(vi.mocked(updateDraft).mock.calls[1]?.[2]?.document.experiences[2]?.source_fact_id).toBeNull()
  })

  it('项目、技能、教育和语言也从档案选择添加，且保留来源关联', async () => {
    const profile = profileFixture()
    const meta = { created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', version: 1 }
    profile.projects.push({ ...meta, id: 'project-2', name: '搜索平台', role: '开发', description: '建设检索服务', achievements: null, tech_stack: ['Python'], url: null, start_date: null, end_date: null, experience_id: null, source_evidence_id: null })
    profile.skills.push({ ...profile.skills[0]!, id: 'skill-2', name: 'Go', name_normalized: 'go' })
    profile.educations.push({ ...meta, id: 'education-2', school: '某大学', major: '计算机', degree: '本科', start_date: null, end_date: null, source_evidence_id: null })
    profile.languages.push({ ...meta, id: 'language-2', language: '英语', level: 'CET-6', note: null, source_evidence_id: null })
    vi.mocked(fetchRevision).mockResolvedValueOnce(revisionFixture(profile))
    const wrapper = mountView()
    await flushPromises()

    for (const [section, id] of [
      ['PROJECTS', 'project-2'], ['SKILLS', 'skill-2'], ['EDUCATIONS', 'education-2'], ['LANGUAGES', 'language-2'],
    ] as const) {
      const picker = wrapper.findAllComponents(Select).find((item) => item.attributes('data-testid') === `source-picker-${section}`)
      expect(picker?.props('options')).toContainEqual(expect.objectContaining({ value: id }))
      picker?.vm.$emit('change', id)
      await wrapper.vm.$nextTick()
      await wrapper.find(`[data-testid="add-selected-${section}"]`).trigger('click')
    }

    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalled(), { timeout: 1800 })
    const saved = vi.mocked(updateDraft).mock.calls.at(-1)?.[2]?.document
    expect(saved?.projects[0]).toMatchObject({ source_fact_id: 'project-2', name: '搜索平台' })
    expect(saved?.skills[1]).toMatchObject({ source_fact_id: 'skill-2', name: 'Go' })
    expect(saved?.educations[0]).toMatchObject({ source_fact_id: 'education-2', school: '某大学' })
    expect(saved?.languages[0]).toMatchObject({ source_fact_id: 'language-2', language: '英语' })
  })

  it('头部短字段和经历条目按双列分组，邮箱与电话各有独立标签', async () => {
    const wrapper = mountView()
    await flushPromises()

    const basics = wrapper.find('.basics-fields')
    expect(basics.exists()).toBe(true)
    expect(basics.text()).toContain('姓名')
    expect(basics.text()).toContain('城市')
    expect(basics.text()).toContain('邮箱')
    expect(basics.text()).toContain('电话')
    expect(wrapper.find('[data-testid="entry-experiences-0"] .entry-fields').exists()).toBe(true)

    await wrapper.find('[data-testid="add-project"]').trigger('click')
    expect(wrapper.find('[data-testid="entry-projects-0"] .entry-fields').exists()).toBe(true)
  })

  it('各模块输入框都有持续可见的中文标签', async () => {
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('[data-testid="add-project"]').trigger('click')
    await wrapper.find('[data-testid="add-education"]').trigger('click')
    await wrapper.find('[data-testid="add-language"]').trigger('click')

    const labels = (selector: string) => wrapper.find(selector).findAll('.ant-form-item-label').map((label) => label.text())
    expect(labels('[data-testid="entry-experiences-0"]')).toEqual([
      '公司', '职位', '地点', '开始时间', '结束时间', '来源经历', '工作要点',
    ])
    expect(labels('[data-testid="entry-projects-0"]')).toEqual([
      '项目名称', '担任角色', '技术栈', '项目链接', '来源项目', '项目说明',
    ])
    expect(labels('[data-testid="entry-skills-0"]')).toEqual([
      '技能名称', '技能分类', '展示分级', '来源技能',
    ])
    expect(labels('[data-testid="entry-educations-0"]')).toEqual([
      '学校', '专业', '学历', '开始时间', '结束时间', '来源教育经历',
    ])
    expect(labels('[data-testid="entry-languages-0"]')).toEqual([
      '语言', '水平', '来源语言能力',
    ])
    for (const section of ['summary', 'experiences', 'projects', 'skills', 'educations', 'languages']) {
      expect(wrapper.find(`[data-testid="panel-${section}"] .ant-form-vertical`).exists()).toBe(true)
    }
  })

  it('技能分类下拉保留既有值，选择和清空后自动保存', async () => {
    const wrapper = mountView()
    await flushPromises()
    const category = wrapper.findAllComponents(Select).find((select) => select.attributes('data-testid') === 'skill-0-category')
    expect(category).toBeDefined()
    expect(category?.props('value')).toBe('编程语言')
    expect(category?.props('options')).toContainEqual({ value: '编程语言', label: '编程语言' })
    expect(category?.props('options')).toContainEqual({ value: '数据库', label: '数据库' })

    category?.vm.$emit('change', '数据库')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    expect(vi.mocked(updateDraft).mock.calls[0]?.[2]?.document.skills[0]?.category).toBe('数据库')

    category?.vm.$emit('change', undefined)
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(2), { timeout: 1800 })
    expect(vi.mocked(updateDraft).mock.calls[1]?.[2]?.document.skills[0]?.category).toBeNull()
  })

  it('技能分级提供常用选项，旧学历手写值不因其他字段保存而丢失', async () => {
    const original = documentFixture()
    original.educations.push({ source_fact_id: null, school: '某大学', major: null, degree: 'MBA', start_date: null, end_date: null })
    vi.mocked(fetchDraft).mockResolvedValueOnce(draftFixture({ document_json: original }))
    const wrapper = mountView()
    await flushPromises()
    const proficiency = wrapper.find('[data-testid="entry-skills-0"]').findComponent({ name: 'AAutoComplete' })
    expect(proficiency.props('options')).toContainEqual({ value: 'ADVANCED', label: '进阶（ADVANCED）' })
    expect((wrapper.find('[data-testid="entry-educations-0"] input[placeholder^="填写其他学历"]').element as HTMLInputElement).value).toBe('MBA')

    await wrapper.find('[data-testid="basics-headline"]').setValue('更新头衔')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    expect(vi.mocked(updateDraft).mock.calls[0]?.[2]?.document.educations[0]?.degree).toBe('MBA')
  })

  it('上传头像后进入实时预览和自动保存，并可移除', async () => {
    const wrapper = mountView()
    await flushPromises()
    const upload = wrapper.findComponent(Upload)
    expect(upload.props('listType')).toBe('picture-card')
    expect(wrapper.find('[data-testid="photo-upload"]').text()).toContain('上传头像')
    const file = new File([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], 'avatar.png', { type: 'image/png' })
    expect((upload.props('beforeUpload') as (file: File) => boolean)(file)).toBe(false)
    await vi.waitFor(() => expect(wrapper.find('[data-testid="preview-photo"]').exists()).toBe(true))
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    expect(vi.mocked(updateDraft).mock.calls[0]?.[2]?.document.contact?.photo_data_url).toMatch(/^data:image\/png;base64,/)

    await wrapper.find('[data-testid="photo-remove"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('[data-testid="preview-photo"]').exists()).toBe(false))
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(2), { timeout: 1800 })
    expect(vi.mocked(updateDraft).mock.calls[1]?.[2]?.document.contact?.photo_data_url).toBeNull()
  })

  it('过大的头像只显示错误，不改变简历', async () => {
    const wrapper = mountView()
    await flushPromises()
    const upload = wrapper.findComponent(Upload)
    const file = new File([new Uint8Array(256 * 1024 + 1)], 'avatar.png', { type: 'image/png' })
    expect((upload.props('beforeUpload') as (file: File) => boolean)(file)).toBe(false)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="photo-error"]').text()).toContain('256 KiB')
    expect(wrapper.find('[data-testid="preview-photo"]').exists()).toBe(false)
    expect(updateDraft).not.toHaveBeenCalled()
  })

  it('没有改动时不发保存请求，左右两栏均可见', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="save-status"]').text()).toBe('已自动保存')
    expect(wrapper.find('[data-testid="resume-form-pane"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="resume-preview-pane"]').exists()).toBe(true)
    expect(updateDraft).not.toHaveBeenCalled()
  })

  it('保存提交整份文档与当前版本号', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="basics-headline"]').setValue('资深后端工程师')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })

    const call = vi.mocked(updateDraft).mock.calls[0]
    expect(call?.[0]).toBe(RESUME_ID)
    expect(call?.[1]).toBe(DRAFT_ID)
    expect(call?.[2]?.version).toBe(1)
    expect(call?.[2]?.document.basics.headline).toBe('资深后端工程师')
    // 整份文档而不是局部字段：未被改动的部分也要一并提交。
    expect(call?.[2]?.document.skills).toHaveLength(1)
    expect(call?.[2]?.document.section_order).toHaveLength(6)
  })

  it('保存成功后采用响应里的新版本号，使下一次保存不会因版本过期失败', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="basics-headline"]').setValue('第一次修改')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    await flushPromises()
    await wrapper.find('[data-testid="basics-headline"]').setValue('第二次修改')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(2), { timeout: 1800 })

    expect(vi.mocked(updateDraft).mock.calls[1]?.[2]?.version).toBe(2)
  })

  it('保存请求未结束时继续输入，不被旧响应覆盖并接着保存新内容', async () => {
    let finishFirst!: (value: ResumeDraft) => void
    vi.mocked(updateDraft).mockImplementationOnce(() => new Promise((resolve) => { finishFirst = resolve }))
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="basics-headline"]').setValue('第一次修改')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    await wrapper.find('[data-testid="basics-headline"]').setValue('第二次修改')
    const firstDocument = vi.mocked(updateDraft).mock.calls[0]?.[2]?.document
    expect(firstDocument?.basics.headline).toBe('第一次修改')
    finishFirst(draftFixture({ version: 2, document_json: firstDocument! }))
    await flushPromises()

    expect((wrapper.find('[data-testid="basics-headline"]').element as HTMLInputElement).value).toBe('第二次修改')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(2), { timeout: 1800 })
    expect(vi.mocked(updateDraft).mock.calls[1]?.[2]).toMatchObject({
      version: 2, document: { basics: { headline: '第二次修改' } },
    })
  })

  it('等待防抖期间离开页面会先保存，不会丢失改动', async () => {
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('[data-testid="basics-headline"]').setValue('离开前修改')
    const guard = vi.mocked(onBeforeRouteLeave).mock.calls.at(-1)?.[0]
    expect(guard).toBeTypeOf('function')
    if (typeof guard !== 'function') return
    expect(await (guard as unknown as () => Promise<boolean>)()).toBe(true)
    expect(updateDraft).toHaveBeenCalledTimes(1)
    expect(vi.mocked(updateDraft).mock.calls[0]?.[2]?.document.basics.headline).toBe('离开前修改')
  })

  it('模块设置面板的改动会随保存一起提交', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="template-management"]').trigger('click')
    await flushPromises()
    const row = await vi.waitFor(() => {
      const element = document.querySelector<HTMLElement>('[data-testid="section-row-EXPERIENCES"]')
      expect(element).not.toBeNull()
      return element!
    })
    row.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true, cancelable: true }))
    await flushPromises()
    document.querySelector<HTMLElement>('[data-testid="section-visibility-SKILLS"]')?.click()
    await flushPromises()
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })

    const savedDoc = vi.mocked(updateDraft).mock.calls[0]?.[2]?.document
    expect(savedDoc?.section_order.slice(0, 2)).toEqual(['EXPERIENCES', 'SUMMARY'])
    expect(savedDoc?.hidden_sections).toEqual(['SKILLS'])
  })

  it('编辑区的模板管理可拖动模块，并立即同步预览及自动保存', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="panel-basics"] [data-testid="template-management"]').exists()).toBe(true)
    await wrapper.find('[data-testid="template-management"]').trigger('click')
    await flushPromises()
    const source = await vi.waitFor(() => {
      const element = document.querySelector<HTMLElement>('[data-testid="section-row-SKILLS"]')
      expect(element).not.toBeNull()
      return element!
    })
    const target = document.querySelector<HTMLElement>('[data-testid="section-row-SUMMARY"]')
    expect(target).not.toBeNull()
    source.dispatchEvent(new Event('dragstart', { bubbles: true }))
    target?.dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }))
    await flushPromises()

    const previewOrder = wrapper.findAll('[data-testid^="preview-section-"]').map((section) => section.attributes('data-testid'))
    expect(previewOrder.slice(0, 2)).toEqual(['preview-section-SKILLS', 'preview-section-SUMMARY'])
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    expect(vi.mocked(updateDraft).mock.calls[0]?.[2]?.document.section_order[0]).toBe('SKILLS')
  })

  it('恢复默认排版后预览和自动保存同步更新，正文不变', async () => {
    const original = documentFixture()
    vi.mocked(fetchDraft).mockResolvedValueOnce(draftFixture({
      document_json: {
        ...original,
        section_order: ['SKILLS', ...original.section_order.filter((section) => section !== 'SKILLS')],
        hidden_sections: ['SUMMARY'],
      },
    }))
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('[data-testid="template-management"]').trigger('click')
    const reset = await vi.waitFor(() => {
      const element = document.querySelector<HTMLElement>('[data-testid="restore-default-layout"]')
      expect(element).not.toBeNull()
      return element!
    })
    reset.click()
    await flushPromises()

    expect(wrapper.find('[data-testid="preview-section-SUMMARY"]').exists()).toBe(true)
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    const saved = vi.mocked(updateDraft).mock.calls[0]?.[2]?.document
    expect(saved?.section_order).toEqual(original.section_order)
    expect(saved?.hidden_sections).toEqual([])
    expect(saved?.summary).toEqual(original.summary)
  })

  it('字段级错误定位到具体条目，而不是只提示"文档非法"', async () => {
    vi.mocked(updateDraft).mockRejectedValueOnce(
      new ApiError({
        code: 'VALIDATION_ERROR',
        message: '简历内容引用了资料修订中不存在的事实。',
        status: 422,
        details: [{ field: 'skills.0.source_fact_id', reason: '事实 abc 不在修订 1 中。' }],
      }),
    )
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="basics-headline"]').setValue('触发保存')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    await flushPromises()

    const marked = wrapper.find('[data-testid="field-error-skills-0"]')
    expect(marked.exists()).toBe(true)
    expect(marked.text()).toContain('不在修订 1 中')
    expect(wrapper.find('[data-testid="action-error"]').text()).toContain('简历内容引用了资料修订中不存在的事实。')
  })

  it('候选稿已处理（409）时提示冲突并停止继续编辑', async () => {
    vi.mocked(updateDraft).mockRejectedValueOnce(
      new ApiError({
        code: 'CONFLICT',
        message: '该候选稿已处理，不能再次确认或丢弃。',
        status: 409,
        details: [{ field: 'status', reason: '当前状态为 CONFIRMED。' }],
      }),
    )
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="basics-headline"]').setValue('触发保存')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    await flushPromises()

    const alert = wrapper.find('[data-testid="action-error"]')
    expect(alert.text()).toContain('该候选稿已处理')
    expect(wrapper.find('[data-testid="retry-save"]').exists()).toBe(true)
  })

  it('网络错误保存失败走全局通知，不在编辑器顶部插入错误块', async () => {
    vi.mocked(updateDraft).mockRejectedValueOnce(
      new ApiError({ code: 'NETWORK_ERROR', message: '无法连接到服务，请确认后端是否已启动。' }),
    )
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="basics-headline"]').setValue('触发保存')
    await vi.waitFor(() => expect(updateDraft).toHaveBeenCalledTimes(1), { timeout: 1800 })
    await flushPromises()

    expect(noticeSpy).toHaveBeenCalledTimes(1)
    expect(noticeSpy.mock.calls[0][0]).toMatchObject({ message: '保存候选稿失败' })
    expect(wrapper.find('[data-testid="action-error"]').exists()).toBe(false)
    // 失败不丢用户已填内容，改完即可重试。
    expect((wrapper.find('[data-testid="basics-headline"]').element as HTMLInputElement).value).toBe('触发保存')
  })
})
