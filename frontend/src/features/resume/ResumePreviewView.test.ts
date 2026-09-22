/**
 * @vitest-environment jsdom
 *
 * 预览页的来源解析与打印入口测试。
 *
 * 关注两点：
 *
 * - 来源必须明确（候选稿或某个版本）。地址里什么都没给时应当提示，而不是渲染一份空白简历——
 *   空白简历看起来像"数据丢了"，会把人引向错误的排查方向；
 * - 打印入口调用的是浏览器自身的 `window.print()`：这是"预览与导出共用同一份 DOM"的实现方式，
 *   因此测试断言的是真实的打印调用，而不是某个导出函数。
 */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/client'
import { fetchDraft, fetchVersion, type ResumeDocument, type ResumeDraft, type ResumeVersion } from '@/shared/api/resume'

import ResumePreviewView from './ResumePreviewView.vue'

const RESUME_ID = 'resume-1'

/** 地址参数；按用例改写它的 `current`。 */
const routeQuery = vi.hoisted(() => ({ current: {} as Record<string, string> }))

vi.mock('vue-router', () => ({ useRoute: () => ({ query: routeQuery.current }) }))

vi.mock('@/shared/api/resume', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/resume')>()
  return {
    ...actual,
    fetchDraft: vi.fn(),
    fetchVersion: vi.fn(),
  }
})

function documentFixture(): ResumeDocument {
  return {
    schema_version: 1,
    basics: { full_name: '张伟', headline: '后端工程师', city: '上海', links: [] },
    contact: null,
    summary: { text: '5 年后端开发经验。', source_fact_id: null },
    experiences: [],
    projects: [],
    skills: [{ source_fact_id: null, name: 'Python', category: null, proficiency: null }],
    educations: [],
    languages: [],
    section_order: ['SUMMARY', 'EXPERIENCES', 'PROJECTS', 'SKILLS', 'EDUCATIONS', 'LANGUAGES'],
    hidden_sections: [],
  }
}

function draftFixture(): ResumeDraft {
  return {
    id: 'draft-1',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
    version: 3,
    resume_id: RESUME_ID,
    base_resume_version_id: null,
    document_json: documentFixture(),
    status: 'DRAFT',
    confirmed_resume_version_id: null,
    generator_name: 'manual',
    generator_version: null,
    failure_code: null,
    failure_message: null,
  }
}

function versionFixture(): ResumeVersion {
  return {
    id: 'version-1',
    resume_id: RESUME_ID,
    version_no: 2,
    profile_revision_id: 'revision-1',
    document_json: documentFixture(),
    render_schema_version: 1,
    created_reason: '确认候选稿生成新版本',
    created_at: '2026-04-01T00:00:00Z',
    evidence_ids: [],
  }
}

function mountView(): VueWrapper {
  return mount(ResumePreviewView, { props: { resumeId: RESUME_ID } })
}

const printSpy = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  routeQuery.current = { draft: 'draft-1' }
  vi.mocked(fetchDraft).mockResolvedValue(draftFixture())
  vi.mocked(fetchVersion).mockResolvedValue(versionFixture())
  vi.stubGlobal('print', printSpy)
})

enableAutoUnmount(afterEach)

describe('ResumePreviewView', () => {
  it('地址里没有来源时给出提示，而不是渲染空白简历', async () => {
    routeQuery.current = {}

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="missing-source"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="resume-preview"]').exists()).toBe(false)
    expect(fetchDraft).not.toHaveBeenCalled()
  })

  it('按候选稿渲染，并标明来源', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(fetchDraft).toHaveBeenCalledWith(RESUME_ID, 'draft-1')
    expect(wrapper.find('[data-testid="preview-name"]').text()).toBe('张伟')
    expect(wrapper.find('[data-testid="source-label"]').text()).toContain('候选稿')
    expect(wrapper.find('[data-testid="preview-section-SKILLS"]').exists()).toBe(true)
  })

  it('按已确认版本渲染，来源里带版本号', async () => {
    routeQuery.current = { version: 'version-1' }

    const wrapper = mountView()
    await flushPromises()

    expect(fetchVersion).toHaveBeenCalledWith('version-1')
    expect(wrapper.find('[data-testid="source-label"]').text()).toContain('v2')
  })

  it('打印按钮调用浏览器的打印', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-testid="print"]').trigger('click')

    expect(printSpy).toHaveBeenCalledTimes(1)
  })

  it('加载失败时显示后端提示，且不渲染预览', async () => {
    vi.mocked(fetchDraft).mockRejectedValueOnce(
      new ApiError({ code: 'RESOURCE_NOT_FOUND', message: '请求的资源不存在。', status: 404 }),
    )

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="load-error"]').text()).toContain('请求的资源不存在。')
    expect(wrapper.find('[data-testid="resume-preview"]').exists()).toBe(false)
  })
})
