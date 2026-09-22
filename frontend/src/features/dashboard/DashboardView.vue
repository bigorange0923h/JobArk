<script setup lang="ts">
/** 统计图与表格使用同一份后端投影，空样本不输出转化率。 */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { init, use, type ECharts } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { requestV1 } from '@/shared/api/client'
import { statusLabels } from '@/shared/api/application'
import { parseServerError } from '@/shared/forms/serverErrors'
use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])
interface Metric { label: string; count: number }
interface Dashboard { pending_jobs: number; application_count: number; funnel: Metric[]; sources: Metric[]; trend: Metric[]; versions: { resume_version_id: string; attempts: number; applied: number; interviewed: number; offered: number }[] }
const stats = ref<Dashboard | null>(null)
const error = ref('')
const chartElement = ref<HTMLElement | null>(null)
let chart: ECharts | undefined
let observer: ResizeObserver | undefined
async function load(): Promise<void> {
  error.value = ''
  try {
    stats.value = await requestV1<Dashboard>('/dashboard')
    await nextTick()
    if (chartElement.value) {
      chart ??= init(chartElement.value)
      chart.setOption({ tooltip: {}, grid: { containLabel: true }, xAxis: { type: 'category', data: stats.value.funnel.map(m => statusLabels[m.label] ?? m.label) }, yAxis: { type: 'value', minInterval: 1 }, series: [{ type: 'bar', data: stats.value.funnel.map(m => m.count) }] })
      observer ??= new ResizeObserver(() => chart?.resize())
      observer.observe(chartElement.value)
    }
  } catch(e) { error.value = parseServerError(e).message }
}
onMounted(load)
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>
<template>
  <section><h1>求职概览</h1><button @click="load">刷新</button><p v-if="error" role="alert">{{ error }}</p>
    <template v-if="stats"><p>待处理职位 {{ stats.pending_jobs }} · 申请尝试 {{ stats.application_count }}</p><p v-if="stats.application_count === 0">暂无申请数据，从职位详情创建申请后将在这里显示。</p>
      <h2>阶段分布</h2><p>按事件中实际到达过该阶段的申请尝试计数；跳过的阶段不推算。</p><div ref="chartElement" style="height:300px" role="img" aria-label="申请阶段柱状图，数值见下表" />
      <table><thead><tr><th>阶段</th><th>尝试数</th></tr></thead><tbody><tr v-for="row in stats.funnel" :key="row.label"><td>{{ statusLabels[row.label] ?? row.label }}</td><td>{{ row.count }}</td></tr></tbody></table>
      <h2>来源分布</h2><p v-if="!stats.sources.length">暂无数据</p><ul><li v-for="row in stats.sources" :key="row.label">{{ row.label === 'MANUAL' ? '手工录入' : row.label }}：{{ row.count }}</li></ul>
      <h2>投递趋势（UTC 日期）</h2><p v-if="!stats.trend.length">暂无投递记录</p><table><tbody><tr v-for="row in stats.trend" :key="row.label"><th>{{ row.label }}</th><td>{{ row.count }}</td></tr></tbody></table>
      <h2>简历版本转化</h2><p>转化率 = 到达阶段的尝试数 / 此版本全部申请尝试数。</p><table><thead><tr><th>版本</th><th>样本</th><th>已投递</th><th>面试</th><th>录用</th><th>面试率</th></tr></thead><tbody><tr v-for="row in stats.versions" :key="row.resume_version_id"><td>{{ row.resume_version_id }}</td><td>{{ row.attempts }}</td><td>{{ row.applied }}</td><td>{{ row.interviewed }}</td><td>{{ row.offered }}</td><td>{{ row.attempts ? `${(100 * row.interviewed / row.attempts).toFixed(1)}%` : '—' }}</td></tr></tbody></table>
    </template>
  </section>
</template>
<style scoped>table{border-collapse:collapse}td,th{padding:.6rem;text-align:left;border-bottom:1px solid #ddd}[role=alert]{color:#b42318}</style>
