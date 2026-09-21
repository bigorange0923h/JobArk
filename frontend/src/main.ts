/** 前端应用入口：创建应用实例并挂载路由。 */

import { createApp } from 'vue'

import App from './App.vue'
import { router } from './app/router'

createApp(App).use(router).mount('#app')
