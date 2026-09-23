<script setup lang="ts">
/** 应用外壳只负责导航与页面布局；业务入口仍由路由表统一定义。 */

import { navItems } from './app/router'
import NavIcon from './app/NavIcon.vue'

// 与 CSS 令牌同源；AntDV 弹层、按钮等不在局部样式作用域内，需要通过 ConfigProvider 设定。
const theme = { token: { colorPrimary: '#165dff', colorText: '#1d2129', borderRadius: 6, fontSize: 14 } }
</script>

<template>
  <a-config-provider :theme="theme">
    <div class="app-shell">
      <aside class="app-sidebar app-header" aria-label="主导航">
        <RouterLink class="brand" to="/" aria-label="JobArk 首页">
          <span class="brand-mark" aria-hidden="true">J</span>
          <span class="brand-copy"><strong>JobArk</strong><small>个人求职工作台</small></span>
        </RouterLink>
        <div class="nav-group-label">工作空间</div>
        <nav class="app-nav" aria-label="功能导航">
          <RouterLink v-for="item in navItems.filter(entry => entry.name !== 'app-status')" :key="item.name" :to="{ name: item.name }">
            <NavIcon v-if="item.icon" :name="item.icon" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>
        <div class="sidebar-foot">
          <RouterLink :to="{ name: 'app-status' }">工程状态</RouterLink>
        </div>
      </aside>
      <div class="app-content">
        <header class="topbar app-header">
          <span class="topbar-title">我的工作台</span>
        </header>
        <main class="app-main"><RouterView /></main>
      </div>
    </div>
  </a-config-provider>
</template>

<style scoped>
.app-shell { min-height: 100vh; display: grid; grid-template-columns: 232px minmax(0, 1fr); font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; }
.app-sidebar { display: flex; flex-direction: column; padding: 24px 12px 16px; background: var(--ja-color-surface); border-right: 1px solid var(--ja-color-border); }
.brand { display: flex; align-items: center; gap: 11px; margin: 0 12px 38px; color: var(--ja-color-text); text-decoration: none; }
.brand-mark { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 8px; background: var(--ja-color-primary); color: #fff; font-size: 19px; font-weight: 700; }
.brand-copy { display: flex; flex-direction: column; line-height: 1.2; }
.brand-copy strong { font-size: 17px; letter-spacing: -0.02em; }
.brand-copy small { margin-top: 4px; color: var(--ja-color-muted); font-size: 11px; font-weight: 500; }
.nav-group-label { padding: 0 14px 10px; color: var(--ja-color-subtle); font-size: 12px; font-weight: 500; }
.app-nav { display: grid; gap: 4px; }
.app-nav a { display: flex; align-items: center; gap: 12px; min-height: 42px; padding: 0 13px; border-radius: 6px; color: #4e5969; text-decoration: none; font-size: 14px; font-weight: 500; transition: background 0.15s ease, color 0.15s ease; }
.app-nav a:hover { color: var(--ja-color-primary); background: #f2f3f5; }
.app-nav a.router-link-active { color: var(--ja-color-primary); background: var(--ja-color-primary-soft); font-weight: 600; }
.app-nav a:focus-visible, .sidebar-foot a:focus-visible, .brand:focus-visible { outline: 2px solid var(--ja-color-primary); outline-offset: 2px; }
.sidebar-foot { margin: auto 12px 0; padding: 16px 2px 0; border-top: 1px solid var(--ja-color-border); font-size: 12px; line-height: 1.6; }
.sidebar-foot a { color: var(--ja-color-muted); text-decoration: none; }
.sidebar-foot a.router-link-active { color: var(--ja-color-primary); }
.app-content { min-width: 0; }
.topbar { display: flex; align-items: center; height: 56px; padding: 0 32px; background: var(--ja-color-surface); border-bottom: 1px solid var(--ja-color-border); }
.topbar-title { color: #4e5969; font-size: 13px; font-weight: 500; }
.app-main { max-width: 1480px; margin: 0 auto; padding: var(--ja-space-page) 32px 64px; }
@media (max-width: 900px) {
  .app-shell { display: block; }
  .app-sidebar { padding: 14px 20px; border-right: 0; border-bottom: 1px solid var(--ja-color-border); }
  .brand { margin: 0 0 14px; }
  .nav-group-label, .topbar { display: none; }
  .app-nav { display: flex; gap: 3px; overflow-x: auto; }
  .app-nav a { flex: 0 0 auto; padding: 0 11px; }
  .sidebar-foot { margin: 8px 10px 0; padding: 0; border-top: 0; font-size: 12px; }
  .app-main { padding: 24px 20px 48px; }
}
</style>
