<script setup lang="ts">
/**
 * 应用根组件：提供最外层布局与路由出口，不承载业务逻辑。
 *
 * 导航暂时只有两项：个人资料是 V1 的起点，工程状态用于确认前后端链路是否打通。
 * 后续 Resume、Jobs、Applications 等页面出现后，这里应改为由路由表驱动的导航，
 * 而不是继续手写链接——那时才有必要引入 AntDV 的 Menu。
 */
</script>

<template>
  <div class="app">
    <header class="app-header">
      <RouterLink class="brand" to="/">JobArk</RouterLink>
      <nav class="app-nav">
        <RouterLink to="/profile">个人资料</RouterLink>
        <RouterLink to="/status">工程状态</RouterLink>
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
