/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { AntDesignVueResolver } from 'unplugin-vue-components/resolvers'
import Components from 'unplugin-vue-components/vite'
import { defineConfig } from 'vite'

// 开发期后端地址。前端代码始终使用相对路径，由 Vite 代理转发，因此本地开发不涉及跨域，
// 也不需要后端开启 CORS；生产部署时前端与后端同源，同样不需要。
const BACKEND_ORIGIN = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [
    vue(),
    // Ant Design Vue 按需自动导入：模板里直接写 `<a-table>` 即可，不必逐个 import。
    // `importStyle: false` 是因为 v4 的组件样式走 CSS-in-JS、由组件自身按需注入，
    // 全局只需在 main.ts 引入一次 reset.css；若开启 importStyle 反而会重复引入样式。
    // 副作用：插件会生成 components.d.ts 供 vue-tsc 识别自动导入的组件，该文件需纳入版本库，
    // 否则干净环境里 `npm run typecheck`（在 vite 之前执行）会因缺少声明而失败。
    Components({ resolvers: [AntDesignVueResolver({ importStyle: false })] }),
  ],
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
    // 默认用 node 环境：传输层测试只需要替换全局 fetch。
    // **组件测试必须在自己文件顶部标注 `@vitest-environment jsdom`**：不能全局改成 jsdom，
    // 因为 jsdom 没有完整实现 `AbortSignal.timeout` 等接口，会让传输层的超时测试在一个与被测
    // 逻辑无关的地方失败（实测如此）。
    environment: 'node',
    include: ['src/**/*.test.ts'],
    // 补齐 jsdom 缺失、而 AntDV 组件挂载时需要的浏览器接口（见该文件内的说明）。
    setupFiles: ['src/test-setup.ts'],
  },
})
