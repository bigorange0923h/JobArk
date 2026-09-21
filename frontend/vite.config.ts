/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 开发期后端地址。前端代码始终使用相对路径，由 Vite 代理转发，因此本地开发不涉及跨域，
// 也不需要后端开启 CORS；生产部署时前端与后端同源，同样不需要。
const BACKEND_ORIGIN = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 业务接口挂 /api/v1，而 /health 是根路径的运维接口，两者都要代理，
      // 否则前端状态页无法通过相对路径访问健康检查。
      '/api': { target: BACKEND_ORIGIN, changeOrigin: true },
      '/health': { target: BACKEND_ORIGIN, changeOrigin: true },
    },
  },
  test: {
    // API Client 的测试只需替换全局 fetch，不需要 DOM 环境。
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
