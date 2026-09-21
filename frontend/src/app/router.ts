/**
 * 应用路由表。
 *
 * 路由只负责页面映射；领域规则、状态流转与权限校验都由后端负责（见 `docs/architecture.md`），
 * 前端不在此处复制业务判断。
 *
 * 业务页面集中在 `features/`，`app/views/` 只保留跨领域的壳页面（工程状态、404）。
 */

import { createRouter, createWebHistory } from 'vue-router'

import ProfileView from '@/features/profile/ProfileView.vue'

import AppStatusView from './views/AppStatusView.vue'
import NotFoundView from './views/NotFoundView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    // 首页进入个人资料：它是 V1 的起点，后续内容都基于这里维护的事实。
    { path: '/', redirect: { name: 'profile' } },
    { path: '/profile', name: 'profile', component: ProfileView },
    // 工程状态页保留为连通性自检入口（前端 → 开发代理 → 后端契约），不属于业务功能。
    { path: '/status', name: 'app-status', component: AppStatusView },
    // 兜底路由：未匹配的地址必须有明确页面，不能停在空白页。
    { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundView },
  ],
})
