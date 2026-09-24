/**
 * 应用路由表。
 *
 * 路由只负责页面映射；领域规则、状态流转与权限校验都由后端负责（见 `docs/architecture.md`），
 * 前端不在此处复制业务判断。
 *
 * 业务页面集中在 `features/`，`app/views/` 只保留跨领域的壳页面（工程状态、404）。
 */

import { createRouter, createWebHistory } from 'vue-router'

const ProfileView = () => import('@/features/profile/ProfileView.vue')
const JobListView = () => import('@/features/job/JobListView.vue')
const ResumeDetailView = () => import('@/features/resume/ResumeDetailView.vue')
const ResumeEditorView = () => import('@/features/resume/ResumeEditorView.vue')
const ResumeListView = () => import('@/features/resume/ResumeListView.vue')
const ResumePreviewView = () => import('@/features/resume/ResumePreviewView.vue')

import AppStatusView from './views/AppStatusView.vue'
import NotFoundView from './views/NotFoundView.vue'

/** 顶部导航项。 */
export interface NavItem {
  /** 路由名；导航只引用路由名，改路径时不必回来改导航。 */
  name: string
  label: string
  /** 左侧导航的语义图标；无需维护无业务意义的序号。 */
  icon?: NavIconName
}

/** 只列当前工作台实际存在的导航语义。 */
export type NavIconName = 'dashboard' | 'profile' | 'resume' | 'job' | 'application' | 'matching' | 'ai'

/**
 * 导航项清单。
 *
 * 导航由路由表驱动而不是在 `App.vue` 里手写链接：两者各写一份的后果是新增页面后导航悄悄缺失，
 * 而"页面存在但进不去"只能靠用户反馈发现。这里只列业务入口，兜底路由不参与导航。
 */
export const navItems: readonly NavItem[] = [
  { name: 'dashboard', label: '概览', icon: 'dashboard' },
  { name: 'profile', label: '个人资料', icon: 'profile' },
  { name: 'resumes', label: '简历', icon: 'resume' },
  { name: 'jobs', label: '职位', icon: 'job' },
  { name: 'applications', label: '申请', icon: 'application' },
  { name: 'matching', label: '匹配', icon: 'matching' },
  // AI 模型配置是基础设施入口：维护服务商、模型与唯一默认模型，不产出业务事实。
  { name: 'ai-models', label: 'AI 模型配置', icon: 'ai' },
  // 工程状态页保留为连通性自检入口（前端 → 开发代理 → 后端契约），不属于业务功能。
  { name: 'app-status', label: '工程状态' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    // 首页先呈现求职进展；个人资料仍可从侧栏进入，不改变事实录入流程。
    { path: '/', redirect: { name: 'dashboard' } },
    { path: '/profile', name: 'profile', component: ProfileView },
    { path: '/jobs', name: 'jobs', component: JobListView },
    { path: '/jobs/:jobId', name: 'job-detail', component: () => import('@/features/job/JobDetailView.vue'), props: true },
    { path: '/applications', name: 'applications', component: () => import('@/features/application/ApplicationView.vue') },
    { path: '/dashboard', name: 'dashboard', component: () => import('@/features/dashboard/DashboardView.vue') },
    { path: '/matching', name: 'matching', component: () => import('@/features/matching/MatchingView.vue') },
    { path: '/ai-models', name: 'ai-models', component: () => import('@/features/ai/AiModelConfigView.vue') },
    { path: '/resumes', name: 'resumes', component: ResumeListView },
    // `props: true` 把路径参数作为 props 传入：页面组件因此不依赖 `useRoute()`，
    // 测试也只需要传 props，不必构造一个路由环境。
    { path: '/resumes/:resumeId', name: 'resume-detail', component: ResumeDetailView, props: true },
    { path: '/resumes/:resumeId/optimize', name: 'resume-optimize', component: () => import('@/features/resume/ResumeOptimizeView.vue'), props: true },
    {
      path: '/resumes/:resumeId/drafts/:draftId',
      name: 'resume-draft-edit',
      component: ResumeEditorView,
      props: true,
    },
    // 预览的来源用查询参数区分（`?draft=` 或 `?version=`），因此只需一条路由；
    // 候选稿与版本的渲染完全一致，分成两条路由会让"渲染规则"有两处入口。
    { path: '/resumes/:resumeId/preview', name: 'resume-preview', component: ResumePreviewView, props: true },
    { path: '/status', name: 'app-status', component: AppStatusView },
    // 兜底路由：未匹配的地址必须有明确页面，不能停在空白页。
    { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundView },
  ],
})
