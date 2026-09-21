<script setup lang="ts">
/** 应用根组件：提供最外层布局与路由出口，不承载业务逻辑。 */
</script>

<template>
  <div class="app">
    <header class="app-header">
      <RouterLink to="/">JobArk</RouterLink>
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
  padding: 0.75rem 1.5rem;
  border-bottom: 1px solid #e5e7eb;
  font-weight: 600;
}

.app-header a {
  color: inherit;
  text-decoration: none;
}

.app-main {
  padding: 1.5rem;
}
</style>
