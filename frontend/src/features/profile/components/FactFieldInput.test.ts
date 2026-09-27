/** @vitest-environment jsdom */
/**
 * 字段控件分派：`kind` 决定用哪个控件。
 *
 * 这里只覆盖容易被改坏的接线——描述符里把 `kind` 写成 `degree` 时，事实弹窗必须真的渲染
 * 学历选择器（而不是一个自由文本框），否则"改了描述符却没有任何效果"不会被任何测试发现。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { FieldDescriptor } from '../types'
import FactFieldInput from './FactFieldInput.vue'

function field(overrides: Partial<FieldDescriptor>): FieldDescriptor {
  return { name: 'degree', label: '学历/学位', kind: 'degree', ...overrides }
}

describe('FactFieldInput', () => {
  it('kind 为 degree 时渲染学历选择器，并原样带入当前值', () => {
    const wrapper = mount(FactFieldInput, { props: { field: field({}), value: '学士' } })

    // 列表外的历史值仍要在界面上可见（见 DegreeField 的用例）。
    expect(wrapper.find('input[placeholder="填写其他学历或学位（如 研究生、MBA）"]').element).toHaveProperty(
      'value',
      '学士',
    )
  })

  it('kind 为 text 时仍渲染普通输入框', () => {
    const wrapper = mount(FactFieldInput, {
      props: { field: field({ name: 'school', label: '学校', kind: 'text' }), value: '乙大学' },
    })

    const input = wrapper.find('input')
    expect(input.element).toHaveProperty('value', '乙大学')
    expect(wrapper.html()).toContain('ant-input')
    // 不该出现选择器的容器。
    expect(wrapper.find('.degree-field').exists()).toBe(false)
  })
})
