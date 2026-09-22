// @vitest-environment jsdom
/**
 * 模块设置面板的交互测试。
 *
 * 验证的是"面板只做两件事、且不越界"：
 *
 * - 顺序调整永远是相邻交换，结果仍是六个模块的完整排列；
 * - 显示开关只改 `hidden_sections`，**不**碰 `section_order`；
 * - 面板不因为某个模块暂时为空就替用户隐藏它——它只提示"不会出现在预览中"。
 *
 * 事件断言用 `attrs` 传入的监听器而不是 `wrapper.emitted()`，理由与 `FactPanel.test.ts` 相同：
 * 后者在这类 SFC 上记录不到 `defineEmits`/`defineModel` 声明的事件，会让"事件没触发"这类结论
 * 真假难辨；监听器是 Vue 的原生机制，最接近运行时行为。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { ResumeDocument, ResumeSection } from '@/shared/api/resume'

import { SECTION_ORDER_DEFAULT, createBlankDocument } from '../document'
import SectionSettingsPanel from './SectionSettingsPanel.vue'

/** 一份有内容的文档：简介与技能有内容，其余模块为空。 */
function documentWithContent(): ResumeDocument {
  return {
    ...createBlankDocument(),
    basics: { full_name: '张伟', headline: null, city: null, links: [] },
    summary: { text: '5 年后端开发经验。', source_fact_id: null },
    skills: [{ source_fact_id: null, name: 'Python', category: null, proficiency: null }],
  }
}

/** 挂载面板并收集它提交的文档。 */
function mountPanel(document: ResumeDocument = documentWithContent()) {
  const submitted: ResumeDocument[] = []
  const wrapper = mount(SectionSettingsPanel, {
    props: { modelValue: document },
    attrs: { 'onUpdate:modelValue': (value: ResumeDocument) => submitted.push(value) },
  })
  return { wrapper, submitted }
}

/** 取最近一次提交的文档；没有提交过时直接失败，而不是让断言在 undefined 上产生误导性结论。 */
function lastSubmitted(submitted: readonly ResumeDocument[]): ResumeDocument {
  const value = submitted[submitted.length - 1]
  if (value === undefined) {
    throw new Error('面板没有提交任何文档。')
  }
  return value
}

describe('SectionSettingsPanel', () => {
  it('按当前顺序列出六个模块', () => {
    const { wrapper } = mountPanel()

    const ids = wrapper.findAll('[data-testid^="section-row-"]').map((row) => row.attributes('data-testid'))

    expect(ids).toEqual(SECTION_ORDER_DEFAULT.map((section) => `section-row-${section}`))
  })

  it('渲染时反映 section_order 的调整结果', () => {
    const document = documentWithContent()
    const reordered: ResumeDocument = {
      ...document,
      section_order: ['SKILLS', ...document.section_order.filter((section) => section !== 'SKILLS')],
    }

    const ids = mountPanel(reordered)
      .wrapper.findAll('[data-testid^="section-row-"]')
      .map((row) => row.attributes('data-testid'))

    expect(ids?.[0]).toBe('section-row-SKILLS')
  })

  it('首项不能上移、末项不能下移', () => {
    const { wrapper } = mountPanel()

    expect(wrapper.find('[data-testid="section-up-SUMMARY"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="section-down-SUMMARY"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-testid="section-down-LANGUAGES"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="section-up-LANGUAGES"]').attributes('disabled')).toBeUndefined()
  })

  it('上移提交交换后的完整顺序', async () => {
    const { wrapper, submitted } = mountPanel()

    await wrapper.find('[data-testid="section-up-EXPERIENCES"]').trigger('click')

    const value = lastSubmitted(submitted)
    expect(value.section_order.slice(0, 2)).toEqual(['EXPERIENCES', 'SUMMARY'])
    expect([...value.section_order].sort()).toEqual([...SECTION_ORDER_DEFAULT].sort())
  })

  it('关闭显示只改 hidden_sections，不动顺序', async () => {
    const { wrapper, submitted } = mountPanel()

    await wrapper.find('[data-testid="section-visibility-SKILLS"]').trigger('click')

    const value = lastSubmitted(submitted)
    expect(value.hidden_sections).toEqual<ResumeSection[]>(['SKILLS'])
    expect(value.section_order).toEqual([...SECTION_ORDER_DEFAULT])
  })

  it('重新打开显示会把模块移出 hidden_sections', async () => {
    const document: ResumeDocument = { ...documentWithContent(), hidden_sections: ['SKILLS'] }
    const { wrapper, submitted } = mountPanel(document)

    await wrapper.find('[data-testid="section-visibility-SKILLS"]').trigger('click')

    expect(lastSubmitted(submitted).hidden_sections).toEqual<ResumeSection[]>([])
  })

  it('空模块只做提示，不会被自动隐藏', () => {
    const { wrapper, submitted } = mountPanel()

    const emptyRow = wrapper.find('[data-testid="section-row-PROJECTS"]')

    expect(emptyRow.text()).toContain('暂无内容')
    expect(emptyRow.find('[data-testid="section-visibility-PROJECTS"]').attributes('aria-checked')).toBe('true')
    // 面板只提示，不提交任何改动：把"暂时为空"变成用户的隐藏选择属于越界。
    expect(submitted).toEqual([])
  })

  it('有内容的模块不显示空提示', () => {
    const { wrapper } = mountPanel()

    expect(wrapper.find('[data-testid="section-row-SUMMARY"]').text()).not.toContain('暂无内容')
  })
})
