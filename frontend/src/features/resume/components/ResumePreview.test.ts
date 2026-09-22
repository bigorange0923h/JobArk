// @vitest-environment jsdom
/**
 * A4 预览的渲染规则测试。
 *
 * 预览是"所见即所得"的承诺所依赖的那一半：屏幕上的预览与打印出来的纸张必须由同一份 DOM 与同一套
 * 规则产生。因此这里验证的重点是**哪些模块会出现在纸上**：
 *
 * - 空模块完全不输出（没有标题、也没有留白），但它不算用户的隐藏选择；
 * - 被显式隐藏的模块即使有内容也不输出；
 * - 顺序完全由 `section_order` 决定。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { ResumeDocument } from '@/shared/api/resume'

import { createBlankDocument } from '../document'
import ResumePreview from './ResumePreview.vue'

/** 一份覆盖主要渲染分支的文档。 */
function previewDocument(overrides: Partial<ResumeDocument> = {}): ResumeDocument {
  return {
    ...createBlankDocument(),
    basics: {
      full_name: '张伟',
      headline: '后端工程师',
      city: '上海',
      links: [{ label: 'GitHub', url: 'https://github.com/example' }],
    },
    contact: { email: 'zhang@example.com', phone: '13800000000' },
    summary: { text: '5 年后端开发经验。', source_fact_id: null },
    experiences: [
      {
        source_fact_id: null,
        company: '某公司',
        title: '后端工程师',
        location: '上海',
        start_date: '2022-03-01',
        end_date: null,
        highlights: ['负责订单系统重构', '把下单耗时降低 30%'],
      },
    ],
    skills: [{ source_fact_id: null, name: 'Python', category: '编程语言', proficiency: 'ADVANCED' }],
    ...overrides,
  }
}

/** 挂载预览。 */
function mountPreview(document: ResumeDocument = previewDocument()) {
  return mount(ResumePreview, { props: { document } })
}

/** 收集实际输出的模块块标识。 */
function sectionIds(wrapper: ReturnType<typeof mountPreview>): (string | undefined)[] {
  return wrapper
    .findAll('[data-testid^="preview-section-"]')
    .map((section) => section.attributes('data-testid')?.replace('preview-section-', ''))
}

describe('ResumePreview', () => {
  it('只输出有内容的模块，空模块连标题都不出现', () => {
    const wrapper = mountPreview()

    expect(sectionIds(wrapper)).toEqual(['SUMMARY', 'EXPERIENCES', 'SKILLS'])
    expect(wrapper.find('[data-testid="preview-section-PROJECTS"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('项目经历')
  })

  it('被显式隐藏的模块即使有内容也不输出', () => {
    const wrapper = mountPreview(previewDocument({ hidden_sections: ['SKILLS'] }))

    expect(sectionIds(wrapper)).toEqual(['SUMMARY', 'EXPERIENCES'])
    expect(wrapper.text()).not.toContain('Python')
  })

  it('模块顺序完全遵循 section_order', () => {
    const document = previewDocument()
    const wrapper = mountPreview({
      ...document,
      section_order: ['SKILLS', ...document.section_order.filter((section) => section !== 'SKILLS')],
    })

    expect(sectionIds(wrapper)[0]).toBe('SKILLS')
  })

  it('渲染姓名、头衔、城市与链接', () => {
    const wrapper = mountPreview()

    expect(wrapper.find('[data-testid="preview-name"]').text()).toBe('张伟')
    expect(wrapper.text()).toContain('后端工程师')
    expect(wrapper.text()).toContain('上海')
    expect(wrapper.find('[data-testid="preview-link-GitHub"]').attributes('href')).toBe('https://github.com/example')
  })

  it('联系方式只输出有值的部分', () => {
    const wrapper = mountPreview(previewDocument({ contact: { email: 'zhang@example.com', phone: null } }))

    expect(wrapper.find('[data-testid="preview-contact"]').text()).toContain('zhang@example.com')
    expect(wrapper.text()).not.toContain('13800000000')
  })

  it('联系方式都没有值时整行不输出', () => {
    const wrapper = mountPreview(previewDocument({ contact: { email: null, phone: null } }))

    expect(wrapper.find('[data-testid="preview-contact"]').exists()).toBe(false)
  })

  it('工作经历按行输出要点', () => {
    const wrapper = mountPreview()

    const items = wrapper.findAll('[data-testid="preview-experience-0"] [data-testid="preview-highlight"]')

    expect(items.map((item) => item.text())).toEqual(['负责订单系统重构', '把下单耗时降低 30%'])
  })

  it('简介为空白时该模块不输出', () => {
    const wrapper = mountPreview(previewDocument({ summary: { text: '   ', source_fact_id: null } }))

    expect(wrapper.find('[data-testid="preview-section-SUMMARY"]').exists()).toBe(false)
  })
})
