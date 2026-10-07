<script setup lang="ts">
/** 当前职位的策略判定、用户确认分类与有原因的单次例外。 */
import { onMounted, ref } from 'vue'
import { Modal } from 'ant-design-vue'
import { confirmExclusionFacts, fetchJob, grantExclusionException, previewExclusion, recordExclusion, type ExclusionEvaluation, type JobOpportunity } from '@/shared/api/job'
import { parseServerError } from '@/shared/forms/serverErrors'

const props = defineProps<{ jobId: string }>()
const job = ref<JobOpportunity | null>(null)
const evaluation = ref<ExclusionEvaluation | null>(null)
const nature = ref<string | null>(null)
const industry = ref<string | null>(null)
const arrangement = ref<string | null>(null)
const reason = ref('')
const busy = ref(false)
const error = ref('')
const exceptionOpen = ref(false)
const industries = [
  ['TECH', '科技'], ['TECH/SOFTWARE', '科技 / 软件'], ['TECH/HARDWARE', '科技 / 硬件'], ['TECH/INTERNET', '科技 / 互联网'],
  ['FINANCE', '金融'], ['FINANCE/BANKING', '金融 / 银行'], ['FINANCE/INSURANCE', '金融 / 保险'], ['FINANCE/SECURITIES', '金融 / 证券'],
  ['MANUFACTURING', '制造'], ['MANUFACTURING/ELECTRONICS', '制造 / 电子'], ['MANUFACTURING/OTHER', '制造 / 其他'],
  ['SERVICES', '服务'], ['SERVICES/HR', '服务 / 人力资源'], ['SERVICES/CONSULTING', '服务 / 咨询'],
].map(([value, label]) => ({ value, label }))
async function load(): Promise<void> {
  error.value = ''
  try {
    job.value = await fetchJob(props.jobId)
    evaluation.value = await previewExclusion(props.jobId)
    nature.value = job.value.company?.nature_code ?? null
    industry.value = job.value.company?.industry_code ?? null
    arrangement.value = job.value.outsourcing_arrangement
  } catch (cause) { error.value = parseServerError(cause).message }
}
async function saveFacts(): Promise<void> {
  if (!job.value?.company || busy.value) return
  busy.value = true; error.value = ''
  try {
    await confirmExclusionFacts(props.jobId, { company_version: job.value.company.version, opportunity_version: job.value.version, nature_code: nature.value, industry_code: industry.value, outsourcing_arrangement: arrangement.value, confirm: true })
    await load()
  } catch (cause) { error.value = parseServerError(cause).message }
  finally { busy.value = false }
}
async function prepare(): Promise<void> {
  busy.value = true; error.value = ''
  try { evaluation.value = await recordExclusion(props.jobId) }
  catch (cause) { error.value = parseServerError(cause).message; evaluation.value = null }
  finally { busy.value = false }
}
async function confirmException(): Promise<void> {
  if (!evaluation.value || reason.value.trim().length < 3) return
  busy.value = true; error.value = ''
  try { evaluation.value = await grantExclusionException(props.jobId, evaluation.value, reason.value.trim()); exceptionOpen.value = false; reason.value = '' }
  catch (cause) { error.value = parseServerError(cause).message }
  finally { busy.value = false }
}
function openException(): void {
  if (!evaluation.value) return
  exceptionOpen.value = true
}
onMounted(load)
</script>

<template>
  <a-card title="求职策略判定" class="section-gap">
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <template v-if="job">
      <p>历史行业文本：{{ job.company?.industry || '无' }}。历史自由文本不会自动归类。</p>
      <a-alert v-if="!job.company" type="info" message="公司身份缺失，公司分类暂不能确认；相关规则保持待核对。" />
      <div class="facts-row">
        <a-form-item label="已确认公司性质"><a-select v-model:value="nature" allow-clear :options="[
          { value: 'OUTSOURCING_PROVIDER', label: '外包服务商' }, { value: 'LABOR_DISPATCH', label: '人力派遣' },
          { value: 'OTHER', label: '其他' },
        ]" /></a-form-item>
        <a-form-item label="已确认行业"><a-select v-model:value="industry" allow-clear show-search option-filter-prop="label" :options="industries" /></a-form-item>
        <a-form-item label="当前岗位安排"><a-select v-model:value="arrangement" allow-clear :options="[
          { value: 'OUTSOURCING', label: '外包项目 / 派遣' }, { value: 'ONSITE', label: '驻场实施' }, { value: 'DIRECT', label: '非外包直招岗位' },
        ]" /></a-form-item>
      </div>
      <a-button :loading="busy" @click="saveFacts">确认并保存分类</a-button>
    </template>
    <div v-if="evaluation" class="evaluation">
      <a-tag :color="evaluation.decision.verdict === 'EXCLUDED' ? 'red' : evaluation.decision.verdict === 'REVIEW' ? 'orange' : 'green'">{{ evaluation.decision.verdict }}</a-tag>
      <span v-if="evaluation.exception_active">当前输入已有单职位例外</span>
      <p v-for="(item, index) in evaluation.decision.reasons" :key="index">{{ item.text }}<span v-if="item.snippet">：{{ item.snippet }}</span></p>
      <p>投递准备核验：{{ evaluation.preparation_allowed ? '可继续人工准备，外部提交仍需单独确认' : '需先核对或登记例外' }}</p>
      <a-space>
        <a-button :loading="busy" @click="prepare">重新评估并记录投递准备</a-button>
        <a-button v-if="evaluation.decision.verdict !== 'ELIGIBLE'" @click="openException">登记本职位临时例外</a-button>
      </a-space>
    </div>
    <Modal v-model:open="exceptionOpen" title="确认本职位临时例外" ok-text="确认登记例外" :confirm-loading="busy" :ok-button-props="{ disabled: reason.trim().length < 3 }" @ok="confirmException">
      <p>例外只对当前职位、JD 快照和规则／资料版本生效，不代表已投递。</p>
      <a-form-item label="例外原因" required><a-textarea v-model:value="reason" :rows="3" :maxlength="1000" /></a-form-item>
    </Modal>
  </a-card>
</template>

<style scoped>
.facts-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: 1rem; }
.evaluation { margin-top: 1rem; }
</style>
