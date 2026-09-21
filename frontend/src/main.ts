/** 前端应用入口：创建应用实例并挂载路由。 */

import { createApp } from 'vue'

// Ant Design Vue v4 的组件样式由 CSS-in-JS 按需注入（见 vite.config.ts 的 resolver 配置），
// 这里只需要一次全局样式重置，否则浏览器默认边距会让布局与组件预期不一致。
import 'ant-design-vue/dist/reset.css'

import App from './App.vue'
import { router } from './app/router'

createApp(App).use(router).mount('#app')
