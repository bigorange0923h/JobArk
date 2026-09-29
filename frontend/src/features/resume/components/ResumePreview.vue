<script setup lang="ts">
/**
 * A4 简历预览。
 *
 * 预览与导出共用这一份 DOM：屏幕上是按 A4 尺寸排版的纸张，打印时由 `src/styles/print.css`
 * 去掉应用外壳并用同一套分页规则输出。这样"看到的"与"另存为 PDF 的"不会出现两套排版。
 *
 * 渲染哪些模块由 `renderedSections` 决定：空模块完全不输出（没有标题、也不留白），
 * 被显式隐藏的模块同样不输出。这里不读取 `hidden_sections` 本身——判定规则只有一处实现，
 * 编辑器与预览才不会各自解释一遍。
 */

import { computed } from 'vue'

import type { ResumeDocument, ResumeSkillItem } from '@/shared/api/resume'

import { SECTION_LABEL, renderedSections } from '../document'

const props = defineProps<{ document: ResumeDocument }>()

/** 实际参与渲染的模块。 */
const sections = computed(() => renderedSections(props.document))

/** 只合并相邻且同分类的技能，避免为了排版打乱用户安排的技能顺序。 */
const skillGroups = computed(() => {
  const groups: { category: string | null; items: ResumeSkillItem[] }[] = []
  for (const item of props.document.skills) {
    const category = item.category?.trim() || null
    const last = groups[groups.length - 1]
    if (last && last.category === category) last.items.push(item)
    else groups.push({ category, items: [item] })
  }
  return groups
})

/**
 * 联系方式中确实有值的部分。
 *
 * 只有一个值时不该留下孤零零的分隔符；两个都没有时整行不输出。
 */
const contactParts = computed(() => {
  const contact = props.document.contact
  if (contact === null) {
    return []
  }
  return [contact.email, contact.phone].filter((value): value is string => value !== null && value.trim() !== '')
})

/**
 * 格式化日期区间。
 *
 * 参数:
 *     start: 开始日期（字符串形式，如 `2022-03-01`）。
 *     end: 结束日期；为空表示仍在进行。
 *     precision: `month` 时只显示到月。工作经历在档案里存的是完整日期（日固定为 1），
 *         直接输出 `2022-03-01` 会让人以为这条经历精确到了某一天。
 *
 * 返回:
 *     string: 展示文本；两端都为空时返回空串，由调用方决定是否输出该片段。
 */
function formatRange(start: string | null, end: string | null, precision: 'day' | 'month' = 'day'): string {
  if (start === null && end === null) {
    return ''
  }
  const side = (value: string | null, fallback: string): string => {
    if (value === null || value === '') {
      return fallback
    }
    return precision === 'month' ? value.slice(0, 7).replace('-', '.') : value
  }
  return `${side(start, '')} – ${side(end, '至今')}`
}
</script>

<template>
  <article class="a4-page" data-testid="resume-preview">
    <header class="preview-header" :class="{ 'has-photo': document.contact?.photo_data_url }">
      <img v-if="document.contact?.photo_data_url" :src="document.contact.photo_data_url" alt="简历头像" class="preview-photo" data-testid="preview-photo" />
      <h1 data-testid="preview-name">{{ document.basics.full_name }}</h1>
      <p v-if="document.basics.headline" class="preview-headline">{{ document.basics.headline }}</p>
      <p class="preview-meta">
        <span v-if="document.basics.city">{{ document.basics.city }}</span>
        <span v-if="contactParts.length > 0" data-testid="preview-contact">{{ contactParts.join(' · ') }}</span>
      </p>
      <p v-if="document.basics.links.length > 0" class="preview-links">
        <a
          v-for="link in document.basics.links"
          :key="link.url"
          :href="link.url"
          :data-testid="`preview-link-${link.label}`"
        >
          {{ link.label }}
        </a>
      </p>
    </header>

    <section
      v-for="section in sections"
      :key="section"
      class="preview-section"
      :data-testid="`preview-section-${section}`"
    >
      <h2>{{ SECTION_LABEL[section] }}</h2>

      <p v-if="section === 'SUMMARY'" class="preview-paragraph">{{ document.summary?.text }}</p>

      <template v-else-if="section === 'EXPERIENCES'">
        <div
          v-for="(item, index) in document.experiences"
          :key="index"
          class="preview-entry"
          :data-testid="`preview-experience-${index}`"
        >
          <p class="preview-entry-title">
            <strong>{{ item.company }}</strong>
            <span>{{ item.title }}</span>
            <span v-if="item.location">{{ item.location }}</span>
            <!-- 工作经历只到月：档案里存的是完整日期，展示时截到月，避免看起来精确到某一天。 -->
            <span v-if="formatRange(item.start_date, item.end_date, 'month')" class="preview-dates">
              {{ formatRange(item.start_date, item.end_date, 'month') }}
            </span>
          </p>
          <div v-if="item.highlights.length > 0" class="preview-highlights">
            <p v-for="(line, lineIndex) in item.highlights" :key="lineIndex" data-testid="preview-highlight">
              {{ line }}
            </p>
          </div>
        </div>
      </template>

      <template v-else-if="section === 'PROJECTS'">
        <div v-for="(item, index) in document.projects" :key="index" class="preview-entry">
          <p class="preview-entry-title">
            <strong>{{ item.name }}</strong>
            <span v-if="item.role">{{ item.role }}</span>
          </p>
          <p v-if="item.description" class="preview-paragraph"><strong class="preview-detail-label">内容：</strong>{{ item.description }}</p>
          <p v-if="item.tech_stack.length > 0" class="preview-tech"><strong class="preview-detail-label">技术栈：</strong>{{ item.tech_stack.join('、') }}</p>
        </div>
      </template>

      <div v-else-if="section === 'SKILLS'" class="preview-skill-list">
        <p v-for="(group, groupIndex) in skillGroups" :key="groupIndex" class="preview-skill-row">
          <strong v-if="group.category" class="preview-skill-category">{{ group.category }}：</strong>
          <template v-for="(item, itemIndex) in group.items" :key="itemIndex"><span>{{ item.name }}<span v-if="item.proficiency">（{{ item.proficiency }}）</span></span><span v-if="itemIndex < group.items.length - 1">、</span></template>
        </p>
      </div>

      <div v-else-if="section === 'EDUCATIONS'">
        <div v-for="(item, index) in document.educations" :key="index" class="preview-entry">
          <p class="preview-entry-title">
            <strong>{{ item.school }}</strong>
            <span v-if="item.major">{{ item.major }}</span>
            <span v-if="item.degree">{{ item.degree }}</span>
            <span v-if="formatRange(item.start_date, item.end_date)" class="preview-dates">
              {{ formatRange(item.start_date, item.end_date) }}
            </span>
          </p>
        </div>
      </div>

      <ul v-else class="preview-inline-list">
        <li v-for="(item, index) in document.languages" :key="index">
          <span>{{ item.language }}</span>
          <span v-if="item.level" class="preview-muted"> · {{ item.level }}</span>
        </li>
      </ul>
    </section>
  </article>
</template>

<style scoped>
/*
 * 尺寸按真实纸张设置：屏幕上看到的分页位置与打印结果一致，用户不必"打印一次才知道"。
 * 纸张留白由元素自身的 padding 提供（而非 `@page` 的 margin），这样屏幕上也能看到真实的边距。
 */
.a4-page {
  box-sizing: border-box;
  width: 210mm;
  min-height: 297mm;
  margin: 0 auto;
  padding: 12mm 10mm;
  background: #fff;
  color: #333;
  font-family: 'Microsoft YaHei', 'PingFang SC', Arial, sans-serif;
  font-size: 10pt;
  line-height: 1.75;
  box-shadow: 0 0 0 1px #e5e7eb;
}

.preview-header {
  position: relative;
  text-align: center;
  padding-bottom: 1mm;
}

.preview-header.has-photo { min-height: 32mm; padding: 0 27mm 1mm; }
.preview-photo { position: absolute; top: 2mm; right: 2mm; width: 24mm; height: 30mm; object-fit: cover; border: 1px solid #ddd; }

.preview-header h1 {
  margin: 0;
  color: #111;
  font-size: 20pt;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.preview-headline {
  margin: 0.25em 0 0;
  color: #444;
  font-size: 9.5pt;
  font-weight: 400;
}

.preview-meta {
  margin: 0.35em 0 0;
  color: #444;
  font-size: 9pt;
}

.preview-meta {
  display: flex;
  justify-content: center;
  gap: 0.75em;
  flex-wrap: wrap;
}

.preview-links {
  display: flex;
  justify-content: center;
  gap: 0.75em;
  margin: 0.2em 0 0;
  color: #444;
  font-size: 9pt;
}
.preview-links a { color: #444; overflow-wrap: anywhere; }

.preview-section {
  margin-top: 8mm;
}

.preview-section > h2 {
  margin: 0 0 0.6em;
  padding-bottom: 0.35em;
  border-bottom: 1px solid #c9c9c9;
  color: #111;
  font-size: 13.5pt;
  font-weight: 700;
  line-height: 1.35;
  break-after: avoid-page;
}

.preview-paragraph {
  margin: 0 0 0.6em;
  white-space: pre-line;
  overflow-wrap: anywhere;
}

.preview-entry {
  margin-bottom: 1.5em;
  /* 经历与教育条目不允许被分页截断：半段经历跨页会让人误读为两段。 */
  break-inside: avoid;
}

.preview-entry-title {
  display: flex;
  align-items: baseline;
  gap: 0.25em 0.65em;
  flex-wrap: wrap;
  margin: 0 0 0.45em;
  line-height: 1.45;
  break-after: avoid-page;
}
.preview-entry-title strong { color: #222; font-size: 10.5pt; font-weight: 700; }
.preview-entry-title span:not(.preview-dates) { color: #444; }

.preview-dates,
.preview-muted,
.preview-tech {
  color: #666;
}

.preview-dates {
  margin-left: auto;
  font-size: 9pt;
  white-space: nowrap;
}

.preview-highlights,
.preview-inline-list {
  margin: 0.2em 0 0;
  padding-left: 0;
}

.preview-highlights p { margin: 0 0 0.4em; overflow-wrap: anywhere; }
.preview-detail-label { color: #333; font-weight: 700; }
.preview-tech { margin: 0.45em 0 0; }
.preview-skill-list { display: grid; gap: 0.35em; }
.preview-skill-row { margin: 0; overflow-wrap: anywhere; }
.preview-skill-category { color: #333; font-weight: 700; }

.preview-inline-list {
  list-style: none;
}
.preview-inline-list li { break-inside: avoid; overflow-wrap: anywhere; }
.preview-inline-list li + li { margin-top: 0.35em; }
.preview-inline-list li > span:first-child { color: #333; font-weight: 600; }

@media print {
  /* 打印时边距由 `@page` 之外的纸张 padding 决定，这里只去掉屏幕上的装饰。 */
  .a4-page {
    width: auto;
    min-height: 0;
    box-shadow: none;
  }
}
</style>
