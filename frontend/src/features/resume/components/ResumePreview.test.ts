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
  it('仅在版本文档有头像时显示右上角头像，旧文档保持居中头部', () => {
    const withoutPhoto = mountPreview()
    expect(withoutPhoto.find('[data-testid="preview-photo"]').exists()).toBe(false)
    expect(withoutPhoto.find('.preview-header').classes()).not.toContain('has-photo')

    const withPhoto = mountPreview(previewDocument({ contact: {
      email: null, phone: null, photo_data_url: 'data:image/png;base64,iVBORw0KGgo=',
    } }))
    expect(withPhoto.find('[data-testid="preview-photo"]').attributes('src')).toContain('data:image/png;base64,')
    expect(withPhoto.find('.preview-header').classes()).toContain('has-photo')
  })
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

  it('模块与经历条目使用明确的标题层级', () => {
    const wrapper = mountPreview(previewDocument({
      projects: [{ source_fact_id: null, name: '订单平台', role: '负责人', description: null, tech_stack: [], url: null }],
      educations: [{ source_fact_id: null, school: '某大学', major: '计算机', degree: '本科', start_date: null, end_date: null }],
    }))

    expect(wrapper.find('[data-testid="preview-name"]').element.tagName).toBe('H1')
    expect(wrapper.findAll('.preview-section > h2').map((heading) => heading.text())).toEqual([
      '个人简介', '工作经历', '项目经历', '技能', '教育经历',
    ])
    expect(wrapper.find('[data-testid="preview-experience-0"] .preview-entry-title strong').text()).toBe('某公司')
    expect(wrapper.find('[data-testid="preview-section-PROJECTS"] .preview-entry-title strong').text()).toBe('订单平台')
    expect(wrapper.find('[data-testid="preview-section-EDUCATIONS"] .preview-entry-title strong').text()).toBe('某大学')
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
    expect(items.every((item) => item.element.tagName === 'P')).toBe(true)
  })

  it('技能按相邻分类成行，但不打乱原条目顺序或虚构空分类', () => {
    const wrapper = mountPreview(previewDocument({ skills: [
      { source_fact_id: null, name: 'Java', category: '后端', proficiency: null },
      { source_fact_id: null, name: 'Spring', category: '后端', proficiency: '熟练' },
      { source_fact_id: null, name: 'Python', category: 'AI 应用', proficiency: null },
      { source_fact_id: null, name: 'Redis', category: '后端', proficiency: null },
      { source_fact_id: null, name: 'Git', category: null, proficiency: null },
    ] }))
    const rows = wrapper.findAll('.preview-skill-row')
    expect(rows.map((row) => row.text())).toEqual([
      '后端：Java、Spring（熟练）', 'AI 应用：Python', '后端：Redis', 'Git',
    ])
  })

  it('项目说明和技术栈使用已有字段展示，不补造参考简历中的业绩', () => {
    const wrapper = mountPreview(previewDocument({ projects: [{
      source_fact_id: null, name: '订单平台', role: '开发', description: '负责订单服务。',
      tech_stack: ['Java', 'Redis'], url: null,
    }] }))
    const project = wrapper.find('[data-testid="preview-section-PROJECTS"]')
    expect(project.text()).toContain('内容：负责订单服务。')
    expect(project.text()).toContain('技术栈：Java、Redis')
    expect(project.text()).not.toContain('业绩：')
  })

  it('工作经历的时间只显示到月，教育经历不受影响', () => {
    const wrapper = mountPreview(
      previewDocument({
        educations: [
          {
            source_fact_id: null,
            school: '某大学',
            major: '计算机',
            degree: '本科',
            start_date: '2016-09-01',
            end_date: '2020-06-30',
          },
        ],
      }),
    )

    // 档案里存的是完整日期（日固定为 1），但工作经历只到月：直接写出来会像精确到了某一天。
    const experiences = wrapper.find('[data-testid="preview-section-EXPERIENCES"]')
    expect(experiences.text()).toContain('2022.03 – 至今')
    expect(experiences.text()).not.toContain('2022-03-01')

    // 教育经历本次不调整，仍按完整日期展示。
    expect(wrapper.find('[data-testid="preview-section-EDUCATIONS"]').text()).toContain('2016-09-01 – 2020-06-30')
  })

  it('简介为空白时该模块不输出', () => {
    const wrapper = mountPreview(previewDocument({ summary: { text: '   ', source_fact_id: null } }))

    expect(wrapper.find('[data-testid="preview-section-SUMMARY"]').exists()).toBe(false)
  })
})
