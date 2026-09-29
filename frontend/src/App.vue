<script setup lang="ts">
/** 应用外壳只负责导航与页面布局；业务入口仍由路由表统一定义。 */

import { navItems } from './app/router'
import NavIcon from './app/NavIcon.vue'
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const sidebarCollapsed = ref(false)
const inResumeEditor = ref(false)

/** 编辑路由默认给预览让出宽度；离开后恢复完整导航，不持久化临时布局选择。 */
watch(() => route.name, (name) => {
  inResumeEditor.value = name === 'resume-draft-edit'
  sidebarCollapsed.value = inResumeEditor.value
}, { immediate: true })

// 与 CSS 令牌同源；AntDV 弹层、按钮等不在局部样式作用域内，需要通过 ConfigProvider 设定。
const theme = { token: { colorPrimary: '#165dff', colorText: '#1d2129', borderRadius: 6, fontSize: 14 } }
</script>

<template>
  <a-config-provider :theme="theme">
    <div class="app-shell" :class="{ 'app-shell--collapsed': sidebarCollapsed, 'app-shell--resume-editor': inResumeEditor }">
      <aside class="app-sidebar app-header" aria-label="主导航">
        <div class="sidebar-head">
          <RouterLink class="brand" to="/" aria-label="JobArk 首页">
            <span class="brand-mark" aria-hidden="true">J</span>
            <span class="brand-copy"><strong>JobArk</strong><small>个人求职工作台</small></span>
          </RouterLink>
        </div>
        <div class="nav-group-label">工作空间</div>
        <nav class="app-nav" aria-label="功能导航">
          <RouterLink v-for="item in navItems.filter(entry => entry.name !== 'app-status')" :key="item.name" :to="{ name: item.name }" :title="sidebarCollapsed ? item.label : undefined" :aria-label="sidebarCollapsed ? item.label : undefined">
            <NavIcon v-if="item.icon" :name="item.icon" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>
        <div class="sidebar-foot">
          <RouterLink :to="{ name: 'app-status' }" :title="sidebarCollapsed ? '工程状态' : undefined" :aria-label="sidebarCollapsed ? '工程状态' : undefined"><span>工程状态</span></RouterLink>
        </div>
        <button v-if="inResumeEditor" type="button" class="sidebar-toggle" :aria-label="sidebarCollapsed ? '展开导航' : '收起导航'" :title="sidebarCollapsed ? '展开导航' : '收起导航'" :aria-expanded="!sidebarCollapsed" data-testid="sidebar-toggle" @click="sidebarCollapsed = !sidebarCollapsed">
          {{ sidebarCollapsed ? '›' : '‹' }}
        </button>
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
.app-shell--collapsed { grid-template-columns: 68px minmax(0, 1fr); }
.app-shell--collapsed .app-sidebar { padding-left: 6px; padding-right: 6px; }
.app-shell--collapsed .sidebar-head { justify-content: center; }
.app-shell--collapsed .brand { margin: 0; }
.app-shell--collapsed .brand-copy, .app-shell--collapsed .app-nav a span, .app-shell--collapsed .sidebar-foot a span { display: none; }
.app-shell--collapsed .nav-group-label { display: none; }
.app-shell--collapsed .app-nav a { justify-content: center; padding: 0; }
.app-shell--collapsed .sidebar-foot { margin-left: 0; margin-right: 0; text-align: center; }
.app-shell--collapsed .sidebar-foot a::after { content: '状态'; }
.app-sidebar { display: flex; flex-direction: column; padding: 24px 12px 16px; background: var(--ja-color-surface); border-right: 1px solid var(--ja-color-border); }
.sidebar-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 34px; margin: 0 8px 38px; }
.brand { display: flex; align-items: center; gap: 11px; min-width: 0; color: var(--ja-color-text); text-decoration: none; }
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
.sidebar-toggle { position: fixed; z-index: 10; top: 50%; left: 231px; transform: translateY(-50%); display: grid; place-items: center; width: 16px; height: 40px; padding: 0; border: 1px solid var(--ja-color-border); border-left: 0; border-radius: 0 6px 6px 0; background: var(--ja-color-surface); box-shadow: 2px 2px 8px rgb(29 33 41 / 8%); color: var(--ja-color-text); cursor: pointer; font-size: 16px; opacity: 0; pointer-events: none; transition: opacity 0.15s ease, color 0.15s ease, background 0.15s ease; }
.app-shell--collapsed .sidebar-toggle { left: 67px; }
.app-sidebar:hover .sidebar-toggle, .app-sidebar:focus-within .sidebar-toggle { opacity: 1; pointer-events: auto; }
.sidebar-toggle:hover { color: var(--ja-color-primary); background: var(--ja-color-primary-soft); }
.sidebar-toggle:focus-visible { outline: 2px solid var(--ja-color-primary); outline-offset: 2px; }
@media (hover: none) and (min-width: 901px) {
  .sidebar-toggle { opacity: 1; pointer-events: auto; }
}
.app-main { max-width: 1480px; margin: 0 auto; padding: var(--ja-space-page) 32px 64px; }
.app-shell--resume-editor .app-main { max-width: none; }
@media (max-width: 900px) {
  .app-shell { display: block; }
  .app-shell--collapsed .app-sidebar { padding: 14px 20px; }
  .app-shell--collapsed .sidebar-head { flex-direction: row; }
  .app-shell--collapsed .nav-group-label { display: none; }
  .app-shell--collapsed .app-nav a { justify-content: flex-start; padding: 0 11px; }
  .app-shell--collapsed .sidebar-foot { margin: 8px 10px 0; text-align: left; }
  .app-shell--collapsed .brand-copy { display: flex; }
  .app-shell--collapsed .app-nav a span, .app-shell--collapsed .sidebar-foot a span { display: initial; }
  .app-shell--collapsed .sidebar-foot a::after { content: none; }
  .app-sidebar { padding: 14px 20px; border-right: 0; border-bottom: 1px solid var(--ja-color-border); }
  .sidebar-head { margin: 0 0 14px; }
  .sidebar-toggle { display: none; }
  .nav-group-label, .topbar { display: none; }
  .app-nav { display: flex; gap: 3px; overflow-x: auto; }
  .app-nav a { flex: 0 0 auto; padding: 0 11px; }
  .sidebar-foot { margin: 8px 10px 0; padding: 0; border-top: 0; font-size: 12px; }
  .app-main { padding: 24px 20px 48px; }
}
</style>
