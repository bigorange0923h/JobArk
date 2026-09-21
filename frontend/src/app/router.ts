/**
 * 应用路由表。
 *
 * 路由只负责页面映射；领域规则、状态流转与权限校验都由后端负责（见 `docs/architecture.md`），
 * 前端不在此处复制业务判断。
 */

import { createRouter, createWebHistory } from 'vue-router'

import AppStatusView from './views/AppStatusView.vue'
import NotFoundView from './views/NotFoundView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'app-status', component: AppStatusView },
    // 兜底路由：未匹配的地址必须有明确页面，不能停在空白页。
    { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundView },
  ],
})
