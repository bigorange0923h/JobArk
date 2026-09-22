/**
 * @vitest-environment jsdom
 *
 * 简历详情页（版本与候选稿）的状态与流转测试。
 *
 * 关注三件容易出错的事：
 *
 * - **确认必须显式选择资料修订**：后端要求提交 `profile_revision_id`，界面不能用"当前最新修订"
 *   悄悄兜底——资料可能在候选稿生成之后被改过，静默沿用会让新版本指向不准确的输入；
 * - **档案未创建时不能新建候选稿**：候选稿的内容来自档案事实，没有档案就没有可填的内容，
 *   此时应给出引导而不是抛出一个失败请求；
 * - 任何写入之后都重新拉取，使界面与后端一致。
 */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { fetchProfile, listRevisions, type Profile } from '@/shared/api/profile'
import {
  confirmDraft,
  createDraft,
  discardDraft,
  fetchResume,
  listDrafts,
  listVersions,
  type Resume,
  type ResumeDraft,
  type ResumeVersion,
} from '@/shared/api/resume'

import ResumeDetailView from './ResumeDetailView.vue'

const { push } = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

vi.mock('@/shared/api/resume', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/resume')>()
  return {
    ...actual,
    fetchResume: vi.fn(),
    listVersions: vi.fn(),
    listDrafts: vi.fn(),
    createDraft: vi.fn(),
    confirmDraft: vi.fn(),
    discardDraft: vi.fn(),
  }
})

vi.mock('@/shared/api/profile', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/profile')>()
  return {
    ...actual,
    fetchProfile: vi.fn(),
    listRevisions: vi.fn(),
  }
})

const RESUME_ID = 'resume-1'

function resumeFixture(): Resume {
  return {
    id: RESUME_ID,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
    name: 'Java 后端',
    target_direction: '后端',
    status: 'ACTIVE',
  }
}

function versionFixture(overrides: Partial<ResumeVersion> = {}): ResumeVersion {
  return {
    id: 'version-1',
    resume_id: RESUME_ID,
    version_no: 1,
    profile_revision_id: 'revision-1',
    document_json: { schema_version: 1 } as ResumeVersion['document_json'],
    render_schema_version: 1,
    created_reason: '首次创建',
    created_at: '2026-02-01T00:00:00Z',
    evidence_ids: [],
    ...overrides,
  }
}

function draftFixture(overrides: Partial<ResumeDraft> = {}): ResumeDraft {
  return {
    id: 'draft-1',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
    version: 1,
    resume_id: RESUME_ID,
    base_resume_version_id: null,
    document_json: { schema_version: 1 } as ResumeDraft['document_json'],
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
    skills: [],
    experiences: [],
    projects: [],
    educations: [],
    languages: [],
    preference: null,
  }
}

function mountView(): VueWrapper {
  return mount(ResumeDetailView, { props: { resumeId: RESUME_ID } })
}

/** 驱动 AntD 下拉的选择。 */
async function selectRevision(wrapper: VueWrapper, revisionId: string): Promise<void> {
  await wrapper.findComponent({ name: 'ASelect' }).vm.$emit('update:value', revisionId)
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchResume).mockResolvedValue(resumeFixture())
  vi.mocked(listVersions).mockResolvedValue([versionFixture()])
  vi.mocked(listDrafts).mockResolvedValue([draftFixture()])
  vi.mocked(fetchProfile).mockResolvedValue(profileFixture())
  vi.mocked(listRevisions).mockResolvedValue([
    {
      id: 'revision-1',
      profile_id: 'profile-1',
      revision_no: 1,
      snapshot_json: {},
      reason: '生成简历',
      created_at: '2026-02-01T00:00:00Z',
    },
  ])
  vi.mocked(createDraft).mockResolvedValue(draftFixture({ id: 'draft-2' }))
  vi.mocked(confirmDraft).mockResolvedValue(versionFixture({ id: 'version-2' }))
  vi.mocked(discardDraft).mockResolvedValue(draftFixture({ status: 'DISCARDED' }))
})

enableAutoUnmount(afterEach)

describe('ResumeDetailView', () => {
  it('加载失败时显示后端提示', async () => {
    vi.mocked(fetchResume).mockRejectedValueOnce(
      new ApiError({ code: 'RESOURCE_NOT_FOUND', message: '请求的资源不存在。', status: 404 }),
    )

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="load-error"]').text()).toContain('请求的资源不存在。')
  })

  it('加载成功后显示版本与候选稿', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Java 后端')
    expect(wrapper.find('[data-testid="version-row-version-1"]').text()).toContain('首次创建')
    expect(wrapper.find('[data-testid="draft-row-draft-1"]').text()).toContain('待确认')
  })

  it('新建候选稿用档案事实生成文档并跳到编辑器', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="create-draft"]').trigger('click')
    await flushPromises()

    const payload = vi.mocked(createDraft).mock.calls[0]?.[1]
    expect(vi.mocked(createDraft).mock.calls[0]?.[0]).toBe(RESUME_ID)
    expect(payload?.document.basics.full_name).toBe('张伟')
    expect(payload?.document.section_order).toHaveLength(6)
    expect(push).toHaveBeenCalledWith({
      name: 'resume-draft-edit',
      params: { resumeId: RESUME_ID, draftId: 'draft-2' },
    })
  })

  it('档案尚未创建时禁用新建并给出引导', async () => {
    vi.mocked(fetchProfile).mockRejectedValueOnce(
      new ApiError({ code: 'RESOURCE_NOT_FOUND', message: '个人档案尚未创建。', status: 404 }),
    )

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="profile-missing-hint"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="create-draft"]').attributes('disabled')).toBeDefined()
  })

  it('未选择资料修订时不提交确认', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="confirm-draft-draft-1"]').trigger('click')
    await flushPromises()

    expect(confirmDraft).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="action-error"]').text()).toContain('资料修订')
  })

  it('选择资料修订后确认候选稿并重新拉取', async () => {
    const wrapper = mountView()
    await flushPromises()

    await selectRevision(wrapper, 'revision-1')
    await wrapper.find('[data-testid="confirm-draft-draft-1"]').trigger('click')
    await flushPromises()

    expect(confirmDraft).toHaveBeenCalledWith(RESUME_ID, 'draft-1', {
      version: 1,
      profile_revision_id: 'revision-1',
    })
    expect(listVersions).toHaveBeenCalledTimes(2)
    expect(listDrafts).toHaveBeenCalledTimes(2)
  })

  it('丢弃候选稿后重新拉取', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="discard-draft-draft-1"]').trigger('click')
    await flushPromises()

    expect(discardDraft).toHaveBeenCalledWith(RESUME_ID, 'draft-1', 1)
    expect(listDrafts).toHaveBeenCalledTimes(2)
  })

  it('已处理的候选稿不能再编辑、确认或丢弃', async () => {
    vi.mocked(listDrafts).mockResolvedValue([draftFixture({ status: 'CONFIRMED' })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="edit-draft-draft-1"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="confirm-draft-draft-1"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="discard-draft-draft-1"]').attributes('disabled')).toBeDefined()
  })

  it('预览候选稿与预览版本分别带上对应的查询参数', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="preview-draft-draft-1"]').trigger('click')
    await wrapper.find('[data-testid="preview-version-version-1"]').trigger('click')

    expect(push).toHaveBeenCalledWith({
      name: 'resume-preview',
      params: { resumeId: RESUME_ID },
      query: { draft: 'draft-1' },
    })
    expect(push).toHaveBeenCalledWith({
      name: 'resume-preview',
      params: { resumeId: RESUME_ID },
      query: { version: 'version-1' },
    })
  })
})
