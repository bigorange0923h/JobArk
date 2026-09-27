/** @vitest-environment jsdom */
/** 城市选择保留旧字符串，且省市选择只提交城市名。 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ProfileCityField from './ProfileCityField.vue'

describe('ProfileCityField', () => {
  it('旧值“上海”能映射到直辖市选项，且不会自行改写档案值', () => {
    const wrapper = mount(ProfileCityField, { props: { value: '上海' } })
    const cascader = wrapper.findComponent({ name: 'ACascader' })
    expect(cascader.exists()).toBe(true)
    expect(cascader.props('value')).toEqual(['上海市', '上海市'])
    expect(wrapper.emitted('updateValue')).toBeUndefined()
  })

  it('选择省市时只提交城市字符串，并触发档案页自动保存', async () => {
    const wrapper = mount(ProfileCityField, { props: { value: '' } })
    const cascader = wrapper.findComponent({ name: 'ACascader' })
    const provinces = cascader.props('options') as Array<{ value: string; children: Array<{ value: string }> }>
    expect(provinces.find((item) => item.value === '黑龙江省')?.children.some((item) => item.value === '哈尔滨市')).toBe(true)

    cascader.vm.$emit('change', ['黑龙江省', '哈尔滨市'])
    expect(wrapper.emitted('updateValue')?.[0]).toEqual(['哈尔滨市'])
    expect(wrapper.emitted('blur')).toHaveLength(1)
  })

  it('列表以外的海外城市仍可回显和手动编辑', () => {
    const wrapper = mount(ProfileCityField, { props: { value: '新加坡' } })
    expect(wrapper.find('[data-testid="city-manual"]').exists()).toBe(false)
    expect(wrapper.find('input[placeholder="填写其他地区或海外城市"]').element).toHaveProperty('value', '新加坡')
  })
})
