<script setup lang="ts">
/** 文档导入只保留临时候选；确认前不把 AI 结果写入档案。 */
import { computed, ref } from 'vue'

import { confirmProfileImport, previewProfileImport, type ProfileImportPreview } from '@/shared/api/profile'
import { parseServerError } from '@/shared/forms/serverErrors'

defineProps<{ hasProfile: boolean }>()
const emit = defineEmits<{ changed: [] }>()

const fileInput = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const contentBase64 = ref('')
const preview = ref<ProfileImportPreview | null>(null)
const consent = ref(false)
const reviewed = ref(false)
const busyPreview = ref(false)
const busyConfirm = ref(false)
const error = ref('')
const result = ref('')
const selectedSkills = ref<number[]>([])
const selectedExperiences = ref<number[]>([])
const selectedEducations = ref<number[]>([])
const busy = computed(() => busyPreview.value || busyConfirm.value)

function chooseFile(): void {
  fileInput.value?.click()
}

/** 换文件即清除旧候选，避免把上一份简历的选择应用到新文件。 */
function onFileChange(event: Event): void {
  const target = event.target as HTMLInputElement
  const next = target.files?.[0] ?? null
  target.value = ''
  file.value = null
  contentBase64.value = ''
  preview.value = null
  reviewed.value = false
  consent.value = false
  result.value = ''
  error.value = ''
  if (!next) return
  if (!/\.(pdf|html|htm)$/i.test(next.name) || next.size === 0 || next.size > 3 * 1024 * 1024) {
    error.value = '请选择不超过 3 MB 的 PDF 或 HTML 简历文件。'
    return
  }
  file.value = next
}

function encodeFile(selected: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('文件读取失败。'))
        return
      }
      resolve(reader.result.split(',', 2)[1] ?? '')
    }
    reader.onerror = () => reject(new Error('文件读取失败。'))
    reader.readAsDataURL(selected)
  })
}

/** 只在明确勾选外部发送确认后生成预览。 */
async function generate(): Promise<void> {
  if (!file.value || !consent.value || busy.value) return
  busyPreview.value = true
  error.value = ''
  result.value = ''
  preview.value = null
  try {
    contentBase64.value = await encodeFile(file.value)
    const next = await previewProfileImport(file.value.name, contentBase64.value, consent.value)
    preview.value = next
    selectedSkills.value = next.candidate.skills.map((_, index) => index)
    selectedExperiences.value = next.candidate.experiences.map((_, index) => index)
    selectedEducations.value = next.candidate.educations.map((_, index) => index)
    reviewed.value = false
  } catch (cause: unknown) {
    error.value = cause instanceof Error && cause.message === '文件读取失败。'
      ? cause.message : parseServerError(cause).message
  } finally {
    busyPreview.value = false
  }
}

type Section = 'skills' | 'experiences' | 'educations'

function toggle(section: Section, index: number, checked: boolean): void {
  const target = section === 'skills' ? selectedSkills : section === 'experiences' ? selectedExperiences : selectedEducations
  target.value = checked ? [...target.value, index] : target.value.filter(value => value !== index)
  reviewed.value = false
}

/** 用户确认后一次性提交；已有基本资料绝不从候选覆盖。 */
async function apply(): Promise<void> {
  if (!preview.value || !file.value || !reviewed.value || busy.value) return
  busyConfirm.value = true
  error.value = ''
  try {
    const saved = await confirmProfileImport({
      filename: file.value.name,
      contentBase64: contentBase64.value,
      preview: preview.value,
      skillIndices: selectedSkills.value,
      experienceIndices: selectedExperiences.value,
      educationIndices: selectedEducations.value,
    })
    result.value = `已${saved.created_profile ? '创建档案并' : ''}导入 ${saved.experiences_added} 段工作经历、${saved.educations_added} 段教育经历和 ${saved.skills_added} 项技能。`
    preview.value = null
    file.value = null
    contentBase64.value = ''
    reviewed.value = false
    consent.value = false
    emit('changed')
  } catch (cause: unknown) {
    error.value = parseServerError(cause).message
  } finally {
    busyConfirm.value = false
  }
}
</script>

<template>
  <a-card title="从已有简历导入" class="import-panel" data-testid="profile-import-panel">
    <p class="import-intro">上传带文字层的 PDF 或 HTML 简历，先预览候选，再选择要写入的内容。原文件不会保存在服务端；扫描件暂不支持 OCR。</p>
    <a-alert v-if="hasProfile" type="info" show-icon message="已有档案只补充经历与技能，不覆盖现有基本信息。" class="import-notice" />
    <div class="file-row">
      <input ref="fileInput" class="file-input" type="file" accept=".pdf,.html,.htm,application/pdf,text/html" aria-label="选择 PDF 或 HTML 简历" @change="onFileChange" />
      <a-button :disabled="busy" data-testid="choose-resume-file" @click="chooseFile">选择简历文件</a-button>
      <span class="file-name">{{ file?.name ?? '尚未选择文件' }}</span>
    </div>
    <a-checkbox v-model:checked="consent" :disabled="!file || busy" data-testid="profile-import-consent">
      我同意将简历提取文字（可能包含姓名、联系方式和工作经历）发送到已配置的 AI 网关
    </a-checkbox>
    <div class="import-actions">
      <a-button type="primary" :loading="busyPreview" :disabled="!file || !consent || busy" data-testid="preview-import" @click="generate">生成待核对候选</a-button>
    </div>
    <a-alert v-if="error" type="error" show-icon :message="error" class="import-notice" data-testid="profile-import-error" />
    <a-alert v-if="result" type="success" show-icon :message="result" class="import-notice" data-testid="profile-import-success" />

    <div v-if="preview" class="candidate" data-testid="profile-import-preview">
      <a-divider>待核对内容</a-divider>
      <p class="candidate-note">以下均是未验证候选，请对照原文摘录逐项检查；取消勾选可排除错误条目。简历只写年份或年月时，日期中的缺失月份/日可能以 1 补位，不表示原文提供了精确日期。</p>
      <dl class="basics-preview">
        <div><dt>姓名</dt><dd>{{ preview.candidate.full_name }}</dd></div>
        <div><dt>头衔</dt><dd>{{ preview.candidate.headline ?? '—' }}</dd></div>
        <div><dt>邮箱</dt><dd>{{ preview.candidate.email ?? '—' }}</dd></div>
        <div><dt>手机</dt><dd>{{ preview.candidate.phone ?? '—' }}</dd></div>
        <div><dt>城市</dt><dd>{{ preview.candidate.city ?? '—' }}</dd></div>
      </dl>
      <p class="source-quote">姓名原文：{{ preview.candidate.name_quote }}</p>
      <section class="candidate-section">
        <h3>工作经历（{{ preview.candidate.experiences.length }}）</h3>
        <a-empty v-if="!preview.candidate.experiences.length" description="未提取到工作经历" />
        <div v-for="(item, index) in preview.candidate.experiences" :key="index" class="candidate-item">
          <a-checkbox :checked="selectedExperiences.includes(index)" @update:checked="(checked: boolean) => toggle('experiences', index, checked)">
            {{ item.company }} · {{ item.title }}（{{ item.start_date }} — {{ item.end_date ?? '至今' }}）
          </a-checkbox>
          <p class="source-quote">原文：{{ item.source_quote }}</p>
        </div>
      </section>
      <section class="candidate-section">
        <h3>教育经历（{{ preview.candidate.educations.length }}）</h3>
        <a-empty v-if="!preview.candidate.educations.length" description="未提取到教育经历" />
        <div v-for="(item, index) in preview.candidate.educations" :key="index" class="candidate-item">
          <a-checkbox :checked="selectedEducations.includes(index)" @update:checked="(checked: boolean) => toggle('educations', index, checked)">
            {{ item.school }} · {{ item.major ?? '专业未提供' }} · {{ item.degree ?? '学历未提供' }}
          </a-checkbox>
          <p class="source-quote">原文：{{ item.source_quote }}</p>
        </div>
      </section>
      <section class="candidate-section">
        <h3>技能（{{ preview.candidate.skills.length }}）</h3>
        <a-empty v-if="!preview.candidate.skills.length" description="未提取到技能" />
        <div v-for="(item, index) in preview.candidate.skills" :key="index" class="candidate-item">
          <a-checkbox :checked="selectedSkills.includes(index)" @update:checked="(checked: boolean) => toggle('skills', index, checked)">{{ item.name }}</a-checkbox>
          <p class="source-quote">原文：{{ item.source_quote }}</p>
        </div>
      </section>
      <a-checkbox v-model:checked="reviewed" data-testid="profile-import-reviewed">我已对照摘录核对所选内容，理解它们会以“未验证”状态写入档案</a-checkbox>
      <div class="import-actions">
        <a-button type="primary" :loading="busyConfirm" :disabled="!reviewed || busy" data-testid="confirm-import" @click="apply">确认写入个人档案</a-button>
      </div>
    </div>
  </a-card>
</template>

<style scoped>
.import-panel { margin-bottom: var(--ja-space-section); }
.import-intro, .candidate-note { color: var(--ja-color-muted); line-height: 1.65; }
.file-row { display: flex; align-items: center; gap: 12px; margin: 16px 0; flex-wrap: wrap; }
.file-input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.file-name { color: var(--ja-color-muted); font-size: 13px; overflow-wrap: anywhere; }
.import-actions, .import-notice { margin-top: 16px; }
.candidate { margin-top: 20px; }
.basics-preview { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.basics-preview div { min-width: 0; padding: 10px 12px; background: var(--ja-color-canvas); border-radius: var(--ja-radius); }
.basics-preview dt { color: var(--ja-color-muted); font-size: 12px; }
.basics-preview dd { margin: 4px 0 0; overflow-wrap: anywhere; }
.candidate-section { margin: 20px 0; }
.candidate-section h3 { margin-bottom: 10px; font-size: 15px; }
.candidate-item { padding: 10px 12px; border: 1px solid var(--ja-color-border); border-radius: var(--ja-radius); margin-bottom: 8px; }
.source-quote { margin: 6px 0 0; color: var(--ja-color-muted); font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
</style>
