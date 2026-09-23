/** @vitest-environment jsdom */
import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import App from './App.vue'

it('侧栏以语义图标和文字导航，不显示数字序号', () => {
  const wrapper = mount(App, {
    global: {
      stubs: {
        AConfigProvider: { template: '<div><slot /></div>' },
        RouterLink: { template: '<a><slot /></a>' },
        RouterView: true,
      },
    },
  })

  expect(wrapper.findAll('.app-nav a')).toHaveLength(6)
  expect(wrapper.findAll('.app-nav .nav-icon')).toHaveLength(6)
  expect(wrapper.find('.nav-index').exists()).toBe(false)
  expect(wrapper.find('.app-nav').text()).toContain('概览')
})
