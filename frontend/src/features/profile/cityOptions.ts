/** 档案城市与求职目标地点共用的本地省市树；只辅助选择，不裁定地址真实性。 */
import { pc } from 'cn-division'

export const CITY_OPTIONS = Object.entries(pc).map(([province, cities]) => ({
  label: province,
  value: province,
  children: Object.keys(cities).filter((city) => city !== '县').map((city) => ({ label: city, value: city })),
}))

export const MANUAL_CITY = '__manual_city__'
export const MANUAL_CITY_OPTION = { label: '其他地区／海外（手动填写）', value: MANUAL_CITY }

/** 两处城市选择器一致地只显示城市名，省份仍通过树路径区分。 */
export function displayCity({ labels }: { labels: string[] }): string {
  return labels.at(-1) ?? ''
}

/** 旧值、城市简称及带省份前缀的策略值都映射到树路径，但不改写原字符串。 */
export function cityPath(value: string): string[] | null {
  const clean = value.trim()
  if (!clean) return null
  for (const province of CITY_OPTIONS) {
    const city = province.children.find((entry) =>
      entry.value === clean || entry.value.replace(/市$/, '') === clean ||
      `${province.value}${entry.value}` === clean,
    )
    if (city) return [province.value, city.value]
  }
  return null
}
