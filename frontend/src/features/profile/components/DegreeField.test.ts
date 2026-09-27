/** @vitest-environment jsdom */
/**
 * 学历选择器：下拉可选，但**不能吃掉列表外的历史值**。
 *
 * 后端 `degree` 是自由字符串，历史数据与模型抽取都可能给出"学士""研究生"这类写法。这里固定三条
 * 行为：列表内可选、列表外原样回显并保留、清空与"其他"的语义。
 *
 * 两处刻意的做法（沿用 `FactPanel.test.ts` 的结论）：
 * - 事件断言用 `attrs` 传入的监听器，而不是 `wrapper.emitted()`：后者在本仓库只记录 DOM 事件，
 *   不记录 `defineEmits` 声明的事件，会让"事件没触发"这类结论真假难辨。
 * - 选值走真实交互（点开下拉、点选项），不直接给子组件 `$emit`：在 AntDV 的组件实例上 emit
 *   并不会触发父组件的监听器，那样写出来的"通过"是假的。下拉渲染在 `document.body` 的传送门里，
 *   因此选项要在 document 上找。
 */

import { enableAutoUnmount, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { DEGREE_OPTIONS } from '../degrees'
import DegreeField from './DegreeField.vue'

enableAutoUnmount(afterEach)

/** 挂载并接住事件；返回的 spy 用于断言，避免依赖不可靠的 `emitted()`。 */
function mountField(value: string) {
  const onUpdateValue = vi.fn()
  const onBlur = vi.fn()
  const wrapper: VueWrapper = mount(DegreeField, {
    props: { value },
    attrs: { onUpdateValue, onBlur },
  })
  return { wrapper, onUpdateValue, onBlur }
}

const MANUAL_PLACEHOLDER = '填写其他学历或学位（如 研究生、MBA）'

/** 打开下拉；选项渲染在 `document.body` 的传送门里。 */
async function openOptions(wrapper: VueWrapper): Promise<void> {
  await wrapper.find('.ant-select-selector').trigger('mousedown')
  await wrapper.find('.ant-select-selector').trigger('click')
  await nextTick()
}

/** 点选下拉里的某一项。 */
async function chooseOption(wrapper: VueWrapper, label: string): Promise<void> {
  await openOptions(wrapper)
  const option = Array.from(document.querySelectorAll('.ant-select-item-option')).find(
    (node) => node.textContent?.trim() === label,
  )
  expect(option).toBeDefined()
  option?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await nextTick()
}

describe('DegreeField', () => {
  it('提供常见学历选项，并保留手动填写入口', async () => {
    const { wrapper } = mountField('')

    await openOptions(wrapper)
    const labels = Array.from(document.querySelectorAll('.ant-select-item-option')).map((node) =>
      node.textContent?.trim(),
    )

    // 期望值直接来自共享定义：在这里重抄一份学历清单，就又会变成两个各自演化的列表。
    for (const degree of DEGREE_OPTIONS) {
      expect(labels).toContain(degree.label)
    }
    // 全日制与非全日制都必须能选：学习形式不能由系统推断，只能用户指定。
    expect(labels).toContain('本科（学士）')
    expect(labels).toContain('本科（非全日制）')
    // 手动入口是控件行为，不是学历值本身（见下面的用例）。
    expect(labels.at(-1)).toBe('其他（手动填写）')
  })

  it('选择列表内的学历时提交该值，并冒泡失焦供自动保存', async () => {
    const { wrapper, onUpdateValue, onBlur } = mountField('')

    await chooseOption(wrapper, '硕士')

    expect(onUpdateValue).toHaveBeenCalledWith('硕士')
    expect(onBlur).toHaveBeenCalledTimes(1)
  })

  it('列表外的历史值原样回显、不自动改写', () => {
    const { wrapper, onUpdateValue } = mountField('学士')

    // 不擅自把"学士"改成"本科"：那等于替用户改档案。
    expect(onUpdateValue).not.toHaveBeenCalled()
    expect(wrapper.find(`input[placeholder="${MANUAL_PLACEHOLDER}"]`).element).toHaveProperty('value', '学士')
  })

  it('选择"其他"时先清空并展开手动输入，输入后照常提交', async () => {
    const { wrapper, onUpdateValue } = mountField('')

    await chooseOption(wrapper, '其他（手动填写）')

    // 提交空字符串而不是哨兵值：哨兵只用于切换控件。
    expect(onUpdateValue).toHaveBeenLastCalledWith('')
    const manual = wrapper.find(`input[placeholder="${MANUAL_PLACEHOLDER}"]`)
    expect(manual.exists()).toBe(true)

    await manual.setValue('MBA')
    expect(onUpdateValue).toHaveBeenLastCalledWith('MBA')
  })

  it('清空已有学历时提交空字符串', async () => {
    const { wrapper, onUpdateValue } = mountField('本科')

    await wrapper.find('.ant-select-clear').trigger('mousedown')
    await nextTick()

    expect(onUpdateValue).toHaveBeenCalledWith('')
  })
})
