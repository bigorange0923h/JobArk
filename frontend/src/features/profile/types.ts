/**
 * Profile 页面里"表单与表格由描述符驱动"所需的类型。
 *
 * 六类事实（证据、技能、经历、项目、教育、语言）的交互完全同构：一份表格 + 一个弹窗表单 +
 * 乐观锁与错误处理。若为每类事实各写一个组件，这六份实现会各自演化（例如某处忘了清除上一次的
 * 字段错误），而它们的差异其实只有字段本身。因此把差异收敛成描述符，把机制收敛成一个面板组件。
 *
 * 描述符的能力边界是刻意限制的：只支持标量字段与标签数组。需要特殊布局或联动逻辑的实体
 * （求职偏好、档案根信息）另有专门组件，不强行塞进这里。
 */

import type { FactApi } from '@/shared/api/profile'

/** 表单字段的控件类型。 */
export type FieldKind = 'text' | 'textarea' | 'number' | 'date' | 'select' | 'tags' | 'evidence'

/** 选项。 */
export interface FieldOption {
  value: string
  label: string
}

/** 一个表单字段。 */
export interface FieldDescriptor {
  /**
   * 字段名。
   *
   * 它同时是表单绑定名、服务端字段级错误的定位名与提交请求体的键，因此**必须与后端请求体
   * 字段名完全一致**。描述符就是界面与后端之间的字段契约。
   */
  name: string
  label: string
  kind: FieldKind
  /** 创建时是否必填。更新时同样适用（表单始终提交全部字段）。 */
  required?: boolean
  /** 文本长度上限，与后端 schema 对齐：提前拦截可以省掉一次必然失败的往返。 */
  maxLength?: number
  /** `select` 的候选项。 */
  options?: FieldOption[]
  placeholder?: string
  /** 字段下方的说明，用于传达约束的**原因**，而不只是重复标签。 */
  help?: string
}

/** 表格的一列。 */
export interface TableColumnDescriptor<TItem> {
  /** 取值字段名，对应事实响应体的字段名。 */
  name: string
  label: string
  /**
   * 展示文本的转换函数。
   *
   * 需要它的情况有两类：枚举值要显示为中文；引用类的值是 id，要显示为被引用对象的名称。
   */
  format?: (item: TItem) => string
}

/** 一类事实在界面上的完整描述。 */
export interface FactDescriptor<TItem extends { id: string }, TPayload> {
  /** 面板标识，同时用于 DOM 的 data-testid，供测试定位。 */
  key: string
  title: string
  description: string
  fields: FieldDescriptor[]
  columns: TableColumnDescriptor<TItem>[]
  /** 该事实的写操作；读取来自档案聚合，不在此处。 */
  operations: FactApi<TItem, TPayload>
  /** 表格行的标题，用于删除确认文案。 */
  rowLabel: (item: TItem) => string
  /** 删除按钮的文案。证据在后端是归档而非物理删除，文案必须如实反映。 */
  removeLabel?: string
  /** 表格中承载该行主标题的列名；不指定时取第一列。 */
  primaryColumn?: string
}

/** 表单值的通用形态：字段名 → 值。 */
export type FieldValues = Record<string, unknown>
