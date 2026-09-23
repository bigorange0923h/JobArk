/** @vitest-environment jsdom */
import { expect, it } from 'vitest'
import { navItems, router } from './router'

it('默认入口和导航首项均指向概览，个人资料保留独立入口', () => {
  expect(router.getRoutes().find(route => route.path === '/')?.redirect).toEqual({ name: 'dashboard' })
  expect(navItems[0]).toEqual({ name: 'dashboard', label: '概览', icon: 'dashboard' })
  expect(router.resolve('/profile').name).toBe('profile')
})
