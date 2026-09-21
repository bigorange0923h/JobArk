/**
 * 组件测试的 DOM 环境补丁。
 *
 * jsdom 没有实现 `matchMedia` 与 `ResizeObserver`，而 Ant Design Vue 的栅格（`a-row`/`a-col`）与
 * 部分组件在挂载时会调用它们。缺这两个接口的表现不是"渲染得不一样"，而是组件直接抛错，
 * 于是所有相关测试都失败在一个与被测逻辑无关的地方。因此在测试环境统一补上最小实现。
 *
 * 本文件对所有测试生效，而多数测试跑在 node 环境（没有 `window`），因此必须先判断环境，
 * 否则会在与被测逻辑无关的地方报 `ReferenceError: window is not defined`。
 */

import { vi } from 'vitest'

if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
}

if (typeof window !== 'undefined' && !('ResizeObserver' in window)) {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  Object.defineProperty(window, 'ResizeObserver', { writable: true, value: ResizeObserverStub })
}
