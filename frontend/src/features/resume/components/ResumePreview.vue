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

import type { ResumeDocument } from '@/shared/api/resume'

import { SECTION_LABEL, renderedSections } from '../document'

const props = defineProps<{ document: ResumeDocument }>()

/** 实际参与渲染的模块。 */
const sections = computed(() => renderedSections(props.document))

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
 *
 * 返回:
 *     string: 展示文本；两端都为空时返回空串，由调用方决定是否输出该片段。
 */
function formatRange(start: string | null, end: string | null): string {
  if (start === null && end === null) {
    return ''
  }
  return `${start ?? ''} – ${end ?? '至今'}`
}
</script>

<template>
  <article class="a4-page" data-testid="resume-preview">
    <header class="preview-header">
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
            <span v-if="formatRange(item.start_date, item.end_date)" class="preview-dates">
              {{ formatRange(item.start_date, item.end_date) }}
            </span>
          </p>
          <ul v-if="item.highlights.length > 0" class="preview-highlights">
            <li v-for="(line, lineIndex) in item.highlights" :key="lineIndex" data-testid="preview-highlight">
              {{ line }}
            </li>
          </ul>
        </div>
      </template>

      <template v-else-if="section === 'PROJECTS'">
        <div v-for="(item, index) in document.projects" :key="index" class="preview-entry">
          <p class="preview-entry-title">
            <strong>{{ item.name }}</strong>
            <span v-if="item.role">{{ item.role }}</span>
          </p>
          <p v-if="item.description" class="preview-paragraph">{{ item.description }}</p>
          <p v-if="item.tech_stack.length > 0" class="preview-tech">{{ item.tech_stack.join(' · ') }}</p>
        </div>
      </template>

      <ul v-else-if="section === 'SKILLS'" class="preview-inline-list">
        <li v-for="(item, index) in document.skills" :key="index">
          <span>{{ item.name }}</span>
          <span v-if="item.category" class="preview-muted"> · {{ item.category }}</span>
          <span v-if="item.proficiency" class="preview-muted"> · {{ item.proficiency }}</span>
        </li>
      </ul>

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
  padding: 16mm 14mm;
  background: #fff;
  color: #111827;
  font-size: 10.5pt;
  line-height: 1.55;
  box-shadow: 0 0 0 1px #e5e7eb;
}

.preview-header {
  text-align: center;
}

.preview-header h1 {
  margin: 0;
  font-size: 18pt;
}

.preview-headline,
.preview-meta {
  margin: 0.2em 0 0;
  color: #4b5563;
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
  color: #4b5563;
}

.preview-section {
  margin-top: 1.1em;
}

.preview-section > h2 {
  margin: 0 0 0.4em;
  padding-bottom: 0.15em;
  border-bottom: 1px solid #9ca3af;
  font-size: 12pt;
}

.preview-paragraph {
  margin: 0 0 0.4em;
}

.preview-entry {
  margin-bottom: 0.6em;
  /* 经历与教育条目不允许被分页截断：半段经历跨页会让人误读为两段。 */
  break-inside: avoid;
}

.preview-entry-title {
  display: flex;
  gap: 0.5em;
  flex-wrap: wrap;
  margin: 0;
}

.preview-dates,
.preview-muted,
.preview-tech {
  color: #6b7280;
}

.preview-dates {
  margin-left: auto;
}

.preview-highlights,
.preview-inline-list {
  margin: 0.2em 0 0;
  padding-left: 1.1em;
}

.preview-inline-list {
  list-style: none;
  padding-left: 0;
}

@media print {
  /* 打印时边距由 `@page` 之外的纸张 padding 决定，这里只去掉屏幕上的装饰。 */
  .a4-page {
    width: auto;
    min-height: 0;
    box-shadow: none;
  }
}
</style>
