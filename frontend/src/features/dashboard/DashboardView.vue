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
const metricColumns = [{ title: '阶段', dataIndex: 'label', key: 'label' }, { title: '尝试数', dataIndex: 'count', key: 'count', align: 'right' as const }]
const versionColumns = [
  { title: '版本', dataIndex: 'resume_version_id', key: 'resume_version_id' },
  { title: '样本', dataIndex: 'attempts', key: 'attempts' },
  { title: '已投递', dataIndex: 'applied', key: 'applied' },
  { title: '面试', dataIndex: 'interviewed', key: 'interviewed' },
  { title: '录用', dataIndex: 'offered', key: 'offered' },
  { title: '面试率', key: 'rate' },
]
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
  <section class="dashboard-view">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">OVERVIEW</p>
        <h1>求职概览</h1>
        <p class="page-subtitle">从职位到申请，掌握当前进展。</p>
      </div>
      <a-button @click="load">刷新数据</a-button>
    </header>
    <a-alert v-if="error" type="error" show-icon :message="error" class="section-gap" role="alert" />
    <template v-if="stats">
      <div class="stat-grid">
        <a-card>
          <a-statistic title="待处理职位" :value="stats.pending_jobs" />
          <span class="stat-note">仍在跟进的机会</span>
        </a-card>
        <a-card>
          <a-statistic title="申请尝试" :value="stats.application_count" />
          <span class="stat-note">已记录的申请次数</span>
        </a-card>
      </div>
      <a-alert v-if="stats.application_count === 0" type="info" show-icon message="暂无申请数据" description="从职位详情选择简历版本创建申请后，这里会展示进度。" class="section-gap" />
      <div class="dashboard-grid">
        <a-card title="阶段分布" class="section-gap">
          <p class="card-hint">按实际到达过的阶段计数，跳过的阶段不推算。</p>
          <div ref="chartElement" class="chart" role="img" aria-label="申请阶段柱状图，数值见下表" />
          <a-table :columns="metricColumns" :data-source="stats.funnel" row-key="label" size="small" :pagination="false">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'label'">{{ statusLabels[record.label] ?? record.label }}</template>
            </template>
          </a-table>
        </a-card>
        <div class="side-panels">
          <a-card title="来源分布" class="section-gap">
            <a-empty v-if="!stats.sources.length" description="暂无来源数据" />
            <a-list v-else :data-source="stats.sources" size="small">
              <template #renderItem="{ item }">
                <a-list-item><span>{{ item.label === 'MANUAL' ? '手工录入' : item.label }}</span><strong>{{ item.count }}</strong></a-list-item>
              </template>
            </a-list>
          </a-card>
          <a-card title="投递趋势（UTC 日期）" class="section-gap">
            <a-empty v-if="!stats.trend.length" description="暂无投递记录" />
            <a-table v-else :columns="[{ title: '日期', dataIndex: 'label' }, { title: '次数', dataIndex: 'count' }]" :data-source="stats.trend" row-key="label" size="small" :pagination="false" />
          </a-card>
        </div>
      </div>
      <a-card title="简历版本转化" class="section-gap">
        <p class="card-hint">面试率 = 到达面试阶段的尝试数 / 此版本全部申请尝试数。</p>
        <a-table :columns="versionColumns" :data-source="stats.versions" row-key="resume_version_id" size="small" :pagination="false">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'rate'">{{ record.attempts ? `${(100 * record.interviewed / record.attempts).toFixed(1)}%` : '—' }}</template>
          </template>
        </a-table>
      </a-card>
    </template>
  </section>
</template>
<style scoped>
.stat-note { display: block; margin-top: 7px; color: var(--ja-color-muted); font-size: 12px; }
.stat-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(260px, 1fr); gap: 16px; }
.side-panels { min-width: 0; }
.chart { height: 270px; }
.card-hint { margin: 0 0 12px; }
:deep(.ant-list-item) { display: flex; justify-content: space-between; }
@media (max-width: 1000px) { .dashboard-grid { grid-template-columns: 1fr; } }
</style>
