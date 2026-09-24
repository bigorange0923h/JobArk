/**
 * @vitest-environment jsdom
 *
 * 工作台外壳的导航契约。
 *
 * 断言与 `navItems` 的**业务入口**保持一致，而不是硬编码数量：新增或移除入口时测试随之变化，
 * 只有"导航与路由表脱节"才会失败。同时必须注入真实 `router` —— 否则 `RouterLink` 无法解析、
 * 渲染成注释节点，断言会退化成"永远为 0"，既不能发现缺入口，也不能发现多余入口。
 */

import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'

import App from './App.vue'
import { navItems, router } from './app/router'

/** 侧栏展示的业务入口；`app-status` 是工程自检入口，固定在侧栏底部单独渲染。 */
const businessEntries = navItems.filter((entry) => entry.name !== 'app-status')

it('侧栏以语义图标和文字导航，不显示数字序号', async () => {
  const wrapper = mount(App, {
    global: {
      plugins: [router],
      stubs: {
        AConfigProvider: { template: '<div><slot /></div>' },
        RouterView: true,
      },
    },
  })
  await router.isReady()

  const links = wrapper.findAll('.app-nav a')
  expect(links).toHaveLength(businessEntries.length)
  // 图标数量必须与"业务入口中有图标的项"一致：漏图标或图标错配都会让这里失败。
  expect(wrapper.findAll('.app-nav .nav-icon')).toHaveLength(businessEntries.filter((entry) => entry.icon).length)
  expect(wrapper.find('.nav-index').exists()).toBe(false)
  const labels = links.map((link) => link.text())
  for (const entry of businessEntries) {
    expect(labels).toContain(entry.label)
  }
  expect(wrapper.find('.app-nav').text()).toContain('概览')
})
