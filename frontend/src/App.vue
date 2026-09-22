<script setup lang="ts">
/**
 * 应用根组件：提供最外层布局与路由出口，不承载业务逻辑。
 *
 * 导航项来自路由表（`app/router.ts` 的 `navItems`）而不是在这里手写：页面增加而导航漏改时，
 * 表现是"页面存在但进不去"，只能靠用户反馈发现。导航项仍保持简单的链接列表，
 * 到入口明显增多时再考虑换用 AntDV 的 Menu。
 */

import { navItems } from './app/router'
</script>

<template>
  <div class="app">
    <header class="app-header">
      <RouterLink class="brand" to="/">JobArk</RouterLink>
      <nav class="app-nav">
        <RouterLink v-for="item in navItems" :key="item.name" :to="{ name: item.name }">
          {{ item.label }}
        </RouterLink>
      </nav>
    </header>
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.app {
  min-height: 100vh;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
}

.app-header {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 0.75rem 1.5rem;
  border-bottom: 1px solid #e5e7eb;
  font-weight: 600;
}

.brand {
  color: inherit;
  text-decoration: none;
}

.app-nav {
  display: flex;
  gap: 1rem;
  font-weight: 400;
}

.app-nav a {
  color: #4b5563;
  text-decoration: none;
}

/* 当前页面高亮，避免用户在多页之间失去位置感。 */
.app-nav a.router-link-active {
  color: #1677ff;
}

.app-main {
  padding: 1.5rem;
}
</style>
