/** @vitest-environment jsdom */
/** 策略地点的省市树要保留旧值，并把新选城市与省份明确对应。 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ProfileTargetLocationsField from './ProfileTargetLocationsField.vue'

describe('ProfileTargetLocationsField', () => {
  it('旧城市简称与海外地点原样回显，未操作时不产生写入', () => {
    const wrapper = mount(ProfileTargetLocationsField, { props: { value: ['上海', '新加坡'] } })
    const tree = wrapper.findComponent({ name: 'ACascader' })
    expect(tree.props('multiple')).toBe(true)
    expect(tree.props('value')).toEqual([['上海市', '上海市']])
    expect(tree.props('placeholder')).toBe('请选择省份和城市')
    expect(wrapper.find('[data-testid="target-location-manual"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('新加坡')
    expect(wrapper.emitted('updateValue')).toBeUndefined()
  })

  it('选择多个城市时保留既有写法，新城市带省份且不丢海外地点', () => {
    const wrapper = mount(ProfileTargetLocationsField, { props: { value: ['上海', '新加坡'] } })
    // 此处只验证旧值保留；真实菜单点击与组件返回值由 StrategyView 的交互用例覆盖。
    wrapper.findComponent({ name: 'ACascader' }).vm.$emit('update:value', [
      ['上海市', '上海市'], ['江苏省', '南京市'],
    ])
    expect(wrapper.emitted('updateValue')?.[0]).toEqual([['上海', '新加坡', '江苏省南京市']])
  })

  it('像个人信息页一样从城市树进入手填，再显式新增和移除地点', async () => {
    const wrapper = mount(ProfileTargetLocationsField, { props: { value: ['新加坡'] } })
    const tree = wrapper.findComponent({ name: 'ACascader' })
    const options = tree.props('options') as Array<{ value: string; label: string }>
    expect(options.at(-1)).toEqual({ value: '__manual_city__', label: '其他地区／海外（手动填写）' })
    tree.vm.$emit('update:value', [['__manual_city__']])
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('updateValue')?.[0]).toEqual([['新加坡']])
    await wrapper.find('[data-testid="target-location-manual"]').setValue('  东京  ')
    await wrapper.find('[data-testid="target-location-add-manual"]').trigger('click')
    expect(wrapper.emitted('updateValue')?.[1]).toEqual([['新加坡', '东京']])

    await wrapper.setProps({ value: ['新加坡', '东京'] })
    await wrapper.findComponent({ name: 'ATag' }).vm.$emit('close')
    expect(wrapper.emitted('updateValue')?.[2]).toEqual([['东京']])
  })
})
