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
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { fetchProfile, type Profile } from '@/shared/api/profile'
import { fetchDraft, updateDraft, type ResumeDocument, type ResumeDraft } from '@/shared/api/resume'

import ResumeEditorView from './ResumeEditorView.vue'

const RESUME_ID = 'resume-1'
const DRAFT_ID = 'draft-1'

const { push } = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

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
    fetchProfile: vi.fn(),
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

function mountView(): VueWrapper {
  return mount(ResumeEditorView, { props: { resumeId: RESUME_ID, draftId: DRAFT_ID } })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchDraft).mockResolvedValue(draftFixture())
  vi.mocked(updateDraft).mockResolvedValue(draftFixture({ version: 2 }))
  vi.mocked(fetchProfile).mockResolvedValue(profileFixture())
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

  it('没有改动时不能保存，避免无意义的往返与版本自增', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="save-draft"]').attributes('disabled')).toBeDefined()
  })

  it('保存提交整份文档与当前版本号', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="basics-headline"]').setValue('资深后端工程师')
    await wrapper.find('[data-testid="save-draft"]').trigger('click')
    await flushPromises()

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
    await wrapper.find('[data-testid="save-draft"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="basics-headline"]').setValue('第二次修改')
    await wrapper.find('[data-testid="save-draft"]').trigger('click')
    await flushPromises()

    expect(vi.mocked(updateDraft).mock.calls[1]?.[2]?.version).toBe(2)
  })

  it('模块设置面板的改动会随保存一起提交', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="section-up-EXPERIENCES"]').trigger('click')
    await wrapper.find('[data-testid="section-visibility-SKILLS"]').trigger('click')
    await wrapper.find('[data-testid="save-draft"]').trigger('click')
    await flushPromises()

    const document = vi.mocked(updateDraft).mock.calls[0]?.[2]?.document
    expect(document?.section_order.slice(0, 2)).toEqual(['EXPERIENCES', 'SUMMARY'])
    expect(document?.hidden_sections).toEqual(['SKILLS'])
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
    await wrapper.find('[data-testid="save-draft"]').trigger('click')
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
    await wrapper.find('[data-testid="save-draft"]').trigger('click')
    await flushPromises()

    const alert = wrapper.find('[data-testid="action-error"]')
    expect(alert.text()).toContain('该候选稿已处理')
    expect(wrapper.find('[data-testid="reload"]').exists()).toBe(true)
  })
})
