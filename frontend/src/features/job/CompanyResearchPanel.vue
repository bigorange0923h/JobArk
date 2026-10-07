<script setup lang="ts">
/** 公司尽调独立状态：联网失败不抹掉保存与匹配；来源和未知均保持可读。 */
import { onMounted, ref, watch } from 'vue'
import { Modal } from 'ant-design-vue'
import { fetchJob } from '@/shared/api/job'
import { requestV1 } from '@/shared/api/client'
import { parseServerError, type ParsedServerError } from '@/shared/forms/serverErrors'

const props = defineProps<{ jobId: string }>()
interface Source { id: string; url: string; title: string; excerpt: string; source_type: string; entity_binding: string; queried_at: string; published_at: string | null }
interface Finding { dimension: string; kind: string; text: string; confidence_reason: string; source_ids: string[]; quotes: string[]; stance: string }
interface Report { id: string; status: string; created_at: string; age_seconds: number; report_json: { sources: Source[]; findings: Finding[]; message?: string; failure_codes?: string[]; boundary?: string } }
interface Capabilities { configured: boolean; provider: string; endpoint: string; data_scope: string; queries: number; sources: number; total_seconds: number; model_service?: string | null; model_name?: string | null }
const reports = ref<Report[]>([])
const capabilities = ref<Capabilities | null>(null)
const companyVersion = ref<number | null>(null)
const legalName = ref('')
const website = ref('')
const city = ref('')
const employerRole = ref('UNKNOWN')
const confirmed = ref(false)
const refresh = ref(false)
const loading = ref(false)
const busy = ref(false)
const open = ref(false)
const error = ref<ParsedServerError | null>(null)
const labels: Record<string, string> = { WAITING_USER: '请先确认公司实体', NOT_CONFIGURED: '搜索服务未配置', UNSUPPORTED: '搜索协议不支持', TIMEOUT: '查询超时', FAILED: '搜索失败', NO_SOURCES: '未找到可用来源', PARTIAL: '部分来源，仍需核对', COMPLETED: '来源报告已生成（不代表通过尽调）' }
const dimensions: Record<string, string> = { RISK: '经营与招聘风险', BUSINESS: '业务发展', TEAM: '团队技术', EXPERIENCE: '工作体验', APPLICABILITY: '个人目标适用性' }
const kinds: Record<string, string> = { FACT: '来源所述事实', INFERENCE: '推测', OPINION: '观点', UNKNOWN: '未知' }

/** 切换立即清空旧输入；整轮读取成功后才发布，慢响应不可覆盖新职位。 */
async function load(): Promise<void> {
  const selected = props.jobId
  reports.value = []; confirmed.value = false; error.value = null; loading.value = true
  legalName.value = ''; website.value = ''; city.value = ''; companyVersion.value = null
  try {
    const [job, history, capability] = await Promise.all([fetchJob(selected), requestV1<Report[]>(`/jobs/${selected}/company-research`), requestV1<Capabilities>('/company-research/capabilities')])
    if (props.jobId !== selected) return
    legalName.value = job.company?.name ?? ''; website.value = job.company?.website_url ?? ''; city.value = job.company?.location ?? ''; companyVersion.value = job.company?.version ?? null
    reports.value = history; capabilities.value = capability
  } catch (cause) { if (props.jobId === selected) error.value = parseServerError(cause) }
  finally { if (props.jobId === selected) loading.value = false }
}

/** 联网必须在告知后确认；保存 WAITING_USER 仍然不会联网。 */
async function research(external = false): Promise<void> {
  if (busy.value || loading.value || !capabilities.value) return
  const selected = props.jobId
  busy.value = true; error.value = null
  try {
    const result = await requestV1<Report>(`/jobs/${selected}/company-research`, { init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ entity_confirmed: confirmed.value, confirm_external: external, company_version: companyVersion.value, legal_name: legalName.value || null, website_url: website.value || null, city: city.value || null, employer_role: employerRole.value, refresh: refresh.value, expected_service: capabilities.value.model_service ?? null, expected_model: capabilities.value.model_name ?? null }) } })
    if (props.jobId === selected) { reports.value = [result, ...reports.value.filter(row => row.id !== result.id)]; open.value = false }
  } catch (cause) { if (props.jobId === selected) error.value = parseServerError(cause) }
  finally { busy.value = false }
}
watch(() => props.jobId, () => void load())
onMounted(() => void load())
</script>

<template>
  <a-card title="公司公开资料尽调（独立步骤）" class="section-gap">
    <a-spin v-if="loading" />
    <a-alert v-if="error" type="error" show-icon :message="error.message" :description="error.requestId ? `错误编号：${error.requestId}` : undefined"><template #action><a-button @click="load">重新读取</a-button></template></a-alert>
    <p>先核对法人及最终雇主。无公司身份、同名歧义、没有来源时不编报告；风险不会计入能力适配分。</p>
    <a-alert v-if="capabilities && !capabilities.configured" type="info" message="独立搜索服务尚未配置；不会用聊天模型自称搜过代替联网。" />
    <a-form layout="vertical">
      <div class="identity-grid"><a-form-item label="法人全称"><a-input v-model:value="legalName" :maxlength="200" :disabled="busy" /></a-form-item><a-form-item label="确认官网（HTTPS）"><a-input v-model:value="website" :maxlength="2048" :disabled="busy" /></a-form-item><a-form-item label="确认城市"><a-input v-model:value="city" :maxlength="100" :disabled="busy" /></a-form-item></div>
      <a-form-item label="招聘主体"><a-select v-model:value="employerRole" :disabled="busy" :options="[{ value: 'UNKNOWN', label: '尚未确认' }, { value: 'EMPLOYER', label: '最终雇主' }, { value: 'AGENCY', label: '猎头/中介' }, { value: 'DISPATCH', label: '派遣方' }]" /></a-form-item>
      <a-checkbox v-model:checked="confirmed" :disabled="busy">我已核对这是要查询的公司实体</a-checkbox>
      <a-checkbox v-model:checked="refresh" :disabled="busy">显式刷新（否则可复用 24 小时报告）</a-checkbox>
      <div class="section-gap"><a-button :loading="busy" :disabled="loading || !capabilities" @click="confirmed && legalName && (website || city) && employerRole !== 'UNKNOWN' ? open = true : research()">{{ confirmed ? '查询公司公开资料' : '记录待确认身份' }}</a-button></div>
    </a-form>
    <Modal v-model:open="open" title="确认公司公开资料联网" ok-text="确认查询" cancel-text="取消" :confirm-loading="busy" @ok="research(true)">
      <p>公司名、官网、城市及招聘主体将发送至 {{ capabilities?.provider ?? '配置的搜索服务' }}（{{ capabilities?.endpoint || '尚未配置' }}）。不发送个人资料或完整 JD。</p>
      <p v-if="capabilities?.model_service">来源摘录交 {{ capabilities.model_service }} 的 {{ capabilities.model_name }} 模型总结。模型配置变更后停止总结，仍保留来源。</p>
      <p v-else>未配置总结模型，本次仅保留搜索来源和未知项。</p>
      <p>预算：最多 {{ capabilities?.queries ?? 6 }} 查询 / {{ capabilities?.sources ?? 8 }} 来源 / {{ capabilities?.total_seconds ?? 90 }} 秒。取消不影响 JD 或本地匹配。</p>
      <a-alert v-if="error" type="error" :message="error.message" />
    </Modal>
    <a-empty v-if="!loading && !reports.length" description="尚未查询，不代表公司已通过尽调" />
    <a-collapse v-if="reports.length" class="section-gap">
      <a-collapse-panel v-for="report in reports" :key="report.id" :header="`${labels[report.status] ?? report.status} · ${new Date(report.created_at).toLocaleString()} · ${(report.age_seconds / 3600).toFixed(1)} 小时前`">
        <a-alert v-if="report.age_seconds >= 86400" type="warning" message="超过 24 小时，请按需刷新；旧报告不会改写。" />
        <p v-if="report.report_json.message">{{ report.report_json.message }}</p><p>{{ report.report_json.boundary }}</p>
        <p v-for="code in report.report_json.failure_codes ?? []" :key="code">未完成步骤：{{ code }}</p>
        <div v-for="(finding, index) in report.report_json.findings" :key="index"><h4>{{ dimensions[finding.dimension] }} · {{ kinds[finding.kind] }}</h4><p>{{ finding.text }}</p><p>来源：{{ finding.source_ids.join('、') || '无' }} · {{ finding.stance }} · {{ finding.confidence_reason }}</p><blockquote v-for="quote in finding.quotes" :key="quote">{{ quote }}</blockquote></div>
        <div v-for="source in report.report_json.sources" :key="source.id"><a :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.id }} · {{ source.title }}</a><p>{{ source.source_type }} · {{ source.entity_binding }} · 发布时间：{{ source.published_at ?? '未知' }} · 查询：{{ source.queried_at }}</p><blockquote>{{ source.excerpt }}</blockquote></div>
      </a-collapse-panel>
    </a-collapse>
  </a-card>
</template>

<style scoped>
.identity-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: 1rem; }
blockquote { margin: 0 0 1rem; padding-left: 1rem; border-left: 2px solid var(--ja-color-muted); }
p, blockquote { overflow-wrap: anywhere; }
</style>
