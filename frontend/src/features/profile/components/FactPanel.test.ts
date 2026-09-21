/**
 * @vitest-environment jsdom
 *
 * 事实面板的机制测试。
 *
 * 被测对象是**机制**而不是某个实体的字段：弹窗表单、必填校验、服务端错误的两种去向
 * （字段级就地提示 / 版本过期需要刷新）。字段与列由描述符提供，这里用一个最小描述符代替真实
 * 实体，避免测试因为某类事实增加了一个字段而失效。
 *
 * 两处刻意的做法：
 * - 事件断言用 `attrs` 传入的监听器，而不是 `wrapper.emitted()`：后者在本组件的泛型 SFC 上
 *   不会记录到 `defineEmits` 声明的事件（实测只记录到 DOM 事件），会让"事件没有触发"这类
 *   结论真假难辨。监听器是 Vue 的原生机制，最接近运行时行为。
 * - 描述符按组件声明的约束类型（`EditableResource` / `unknown`）书写，而不是测试内部的具体
 *   子类型：测试框架无法从 SFC 的泛型参数推断出具体类型，写成子类型会直接导致类型检查失败。
 *   分组入口处需要读取具体字段时，再用一个带注释的收窄函数处理。
 */

import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { EditableResource } from '@/shared/api/profile'
import { ApiError } from '@/shared/api/client'

import type { FactDescriptor } from '../types'
import FactPanel from './FactPanel.vue'

/** 测试用的行数据：在公共字段之外多一个展示名。 */
interface StubItem extends EditableResource {
  name: string
}

function stubItem(): StubItem {
  return {
    id: 'item-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
    name: 'Python',
  }
}

/** 读取展示名；描述符按约束类型声明，这里收窄回测试的具体类型。 */
function stubName(item: EditableResource): string {
  return (item as StubItem).name
}

const create = vi.fn(async (_payload: unknown): Promise<EditableResource> => stubItem())
const update = vi.fn(async (_id: string, _payload: unknown): Promise<EditableResource> => stubItem())
const remove = vi.fn(async (_id: string): Promise<{ id: string }> => ({ id: 'item-1' }))

const descriptor: FactDescriptor<EditableResource, unknown> = {
  key: 'stub',
  title: '测试事实',
  description: '用于验证面板机制。',
  rowLabel: stubName,
  operations: { create, update, remove },
  fields: [
    { name: 'name', label: '名称', kind: 'text', required: true, maxLength: 100 },
    { name: 'evidence', label: '来源证据', kind: 'evidence', options: [{ value: 'e1', label: '证书一' }] },
  ],
  columns: [{ name: 'name', label: '名称' }],
}

/** 挂载面板，并把 `changed`/`conflict` 事件接到可断言的监听器上。 */
function mountPanel(items: readonly EditableResource[] = []) {
  const onChanged = vi.fn()
  const onConflict = vi.fn()
  const wrapper: VueWrapper = mount(FactPanel, {
    props: { descriptor, items },
    attrs: { onChanged, onConflict },
  })
  return { wrapper, onChanged, onConflict }
}

/**
 * 归一化按钮文案后按文案点击。
 *
 * 归一化是必要的：Ant Design 会在两个汉字的按钮文案之间插入空格（渲染为 `新 增`），
 * 直接按原文案比较会失败，而失败信息看起来像是"按钮不存在"。
 */
async function clickButton(wrapper: VueWrapper, text: string): Promise<void> {
  const buttons = wrapper.findAll('button')
  const target = text.replace(/[\s\u200b]/g, '')
  const button = buttons.find((candidate) => candidate.text().replace(/[\s\u200b]/g, '') === target)
  if (button === undefined) {
    const found = buttons.map((candidate) => JSON.stringify(candidate.text())).join(', ')
    throw new Error(`没有找到按钮「${text}」；当前按钮为：${found}`)
  }
  await button.trigger('click')
}

beforeEach(() => {
  vi.clearAllMocks()
})

/** 每个用例后卸载组件，避免上一个用例的弹窗状态影响下一个。 */
enableAutoUnmount(afterEach)

describe('FactPanel', () => {
  it('必填项为空时拦下提交，不发起请求，并指出缺失字段', async () => {
    const { wrapper } = mountPanel()

    await clickButton(wrapper, '新增')
    await clickButton(wrapper, '保存')
    await flushPromises()

    expect(create).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('该项为必填。')
  })

  it('把 422 的字段级原因显示在对应字段下，且不要求整页刷新', async () => {
    update.mockRejectedValueOnce(
      new ApiError({
        code: 'VALIDATION_ERROR',
        message: '提交的数据未通过校验。',
        status: 422,
        details: [{ field: 'name', reason: '名称过长。' }],
      }),
    )
    const { wrapper, onChanged, onConflict } = mountPanel([stubItem()])

    await clickButton(wrapper, '编辑')
    await clickButton(wrapper, '保存')
    await flushPromises()

    expect(update).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('名称过长。')
    // 弹窗保持打开，用户可以就地修正；不应触发整页重载。
    expect(wrapper.find('.ant-modal').exists()).toBe(true)
    expect(onChanged).not.toHaveBeenCalled()
    expect(onConflict).not.toHaveBeenCalled()
  })

  it('版本过期（409 且带 version 细节）时通知页面刷新并关闭弹窗', async () => {
    update.mockRejectedValueOnce(
      new ApiError({
        code: 'CONFLICT',
        message: '记录已被更新，请刷新后重试。',
        status: 409,
        details: [{ field: 'version', reason: '当前版本为 2，提交的是 1。' }],
      }),
    )
    const { wrapper, onChanged, onConflict } = mountPanel([stubItem()])

    await clickButton(wrapper, '编辑')
    await clickButton(wrapper, '保存')
    await flushPromises()

    expect(onConflict).toHaveBeenCalledWith('记录已被更新，请刷新后重试。')
    expect(onChanged).not.toHaveBeenCalled()
    expect(wrapper.find('.ant-modal').exists()).toBe(false)
  })

  it('其他 409（例如重名）只在字段上提示，不要求整页刷新', async () => {
    update.mockRejectedValueOnce(
      new ApiError({
        code: 'CONFLICT',
        message: '该技能已存在。',
        status: 409,
        details: [{ field: 'name', reason: '规范化名称 python 已被占用。' }],
      }),
    )
    const { wrapper, onConflict } = mountPanel([stubItem()])

    await clickButton(wrapper, '编辑')
    await clickButton(wrapper, '保存')
    await flushPromises()

    expect(update).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('规范化名称 python 已被占用。')
    expect(onConflict).not.toHaveBeenCalled()
  })

  it('保存成功时提交完整字段并通知页面重新加载', async () => {
    const { wrapper, onChanged, onConflict } = mountPanel([stubItem()])

    await clickButton(wrapper, '编辑')
    await clickButton(wrapper, '保存')
    await flushPromises()

    expect(update).toHaveBeenCalledWith('item-1', { name: 'Python', evidence: null, version: 1 })
    expect(onChanged).toHaveBeenCalledTimes(1)
    expect(onConflict).not.toHaveBeenCalled()
  })
})
