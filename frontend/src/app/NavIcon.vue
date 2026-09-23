<script setup lang="ts">
/** 导航图标只表达现有业务入口，颜色随链接状态变化。 */
import type { NavIconName } from './router'

defineProps<{ name: NavIconName }>()
</script>

<template>
  <svg
    class="nav-icon"
    width="18"
    height="18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <template v-if="name === 'dashboard'">
      <rect x="3" y="3" width="7" height="7" rx="1.4" />
      <rect x="14" y="3" width="7" height="7" rx="1.4" />
      <rect x="3" y="14" width="7" height="7" rx="1.4" />
      <rect x="14" y="14" width="7" height="7" rx="1.4" />
    </template>
    <template v-else-if="name === 'profile'">
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20v-1.5a7 7 0 0 1 14 0V20" />
    </template>
    <template v-else-if="name === 'resume'">
      <path d="M6 3.5h8l4 4V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" />
      <path d="M14 3.5V8h4M8 12h7M8 16h7" />
    </template>
    <template v-else-if="name === 'job'">
      <rect x="3" y="7" width="18" height="14" rx="2" />
      <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18M10 12v2h4v-2" />
    </template>
    <template v-else-if="name === 'application'">
      <path d="M9 4h6M7 5H6a2 2 0 0 0-2 2v13a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V7a2 2 0 0 0-2-2h-1" />
      <rect x="8" y="3" width="8" height="4" rx="1" />
      <path d="m8 15 2.5 2.5L16 12" />
    </template>
    <template v-else-if="name === 'matching'">
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
    </template>
  </svg>
</template>

<style scoped>
.nav-icon { flex: 0 0 18px; }
</style>
