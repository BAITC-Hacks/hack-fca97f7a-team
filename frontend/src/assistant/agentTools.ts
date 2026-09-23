import type { ForecastHour, ForecastResult } from '../types'
import { decimal, percent, signedPoints } from '../ru.ts'
import { dayLabel, hourLabel } from '../timeline/format.ts'

export type Intent = 'earth' | 'analytics' | 'minimum' | 'maximum' | 'ramp' | 'tomorrow' | 'here' | 'navigate' | 'question' | 'limitations'
export interface UICommand { intent: Intent, turbineId?: string, tomorrow: boolean }

// An explicit local allowlist. This parser is never represented as an LLM tool call.
export function parseUICommand(text: string): UICommand {
  const value = text.toLocaleLowerCase('ru').replaceAll('ё', 'е')
  const turbine = value.match(/(?:\b[tт]\s*|турбин\S*\s*|turbine\s*)(\d+)\b/)
  const turbineId = turbine ? `T${turbine[1]}` : undefined
  const tomorrow = /завтра|tomorrow/.test(value)
  const intent: Intent = /на землю|к земле|глобус|обзор земли|back to earth|global view/.test(value) ? 'earth'
    : /график|аналитик|таблиц|analytics|chart/.test(value) ? 'analytics'
    : /неопределен|точност|уверен|надежн|довер|confidence|uncertainty/.test(value) ? 'limitations'
    : /шесть|шести|шестичас|6\s*час|six.?hour/.test(value) ? 'question'
    : /миним|самая низ|самая мал|наименьш|lowest|minimum/.test(value) ? 'minimum'
    : /максим|самая высок|наибольш|highest|maximum/.test(value) ? 'maximum'
    : /самое сильное|самый больш|сильнейш|резк|biggest|ramp/.test(value) && /паден|сниж|спад|изменен|drop|ramp/.test(value) ? 'ramp'
    : /здесь|этот час|этого часа|этот период|here|this period/.test(value) ? 'here'
    : tomorrow && /покаж|что будет|что произойдет|show|happen/.test(value) ? 'tomorrow'
    : turbineId && /покаж|перей|открой|выбер|show|open|go/.test(value) ? 'navigate'
    : 'question'
  return { intent, turbineId, tomorrow }
}

export function localDate(stamp: string, zone: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(stamp))
  const read = (type: string) => parts.find(part => part.type === type)?.value || ''
  return `${read('year')}-${read('month')}-${read('day')}`
}

export function tomorrowDate(result: ForecastResult): string {
  const originDay = localDate(result.origin, result.timezone)
  const date = new Date(`${originDay}T12:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 1)
  return date.toISOString().slice(0, 10)
}

export function selectForecastHour(result: ForecastResult, intent: Intent, tomorrow = false): number | null {
  const wanted = tomorrowDate(result)
  const candidates = result.hours.map((hour, index) => ({ hour, index })).filter(({ hour }) => !tomorrow || localDate(hour.valid_at, result.timezone) === wanted)
  if (!candidates.length) return null
  if (intent === 'tomorrow' || intent === 'navigate') return candidates[0].index
  if (intent === 'ramp') {
    const changes = candidates.filter(({ index }) => index > 0).map(({ hour, index }) => ({ index, delta: hour.power_norm - result.hours[index - 1].power_norm }))
    if (!changes.length) return null
    return changes.reduce((best, row) => row.delta < best.delta ? row : best).index
  }
  const chooseMin = intent === 'minimum'
  return candidates.reduce((best, row) => (chooseMin ? row.hour.power_norm < best.hour.power_norm : row.hour.power_norm > best.hour.power_norm) ? row : best).index
}

export function explainSelectedHour(result: ForecastResult, index: number): string {
  const hour = result.hours[index]
  const previous = result.hours[index - 1]
  const change = previous ? ` За час: ${signedPoints(hour.power_norm - previous.power_norm)}; ветер ${decimal(previous.wind_speed_ms)} → ${decimal(hour.wind_speed_ms)} м/с.` : ' Это первый час выбранного прогноза.'
  return `${dayLabel(hour.valid_at, result.timezone)}, ${hourLabel(hour.valid_at, result.timezone)}: ${percent(hour.power_norm)} нормализованной мощности, ветер ${decimal(hour.wind_speed_ms)} м/с, температура ${decimal(hour.temperature_c)} °C.${change} Модель использует ветер и температуру. Эти значения показывают связь прогноза с признаками, но не доказывают причину изменения.`
}

export function seekDescription(result: ForecastResult, index: number, intent: Intent): string {
  const hour: ForecastHour = result.hours[index]
  const name = intent === 'minimum' ? 'Минимум' : intent === 'maximum' ? 'Максимум' : intent === 'ramp' ? 'Наибольшее почасовое снижение' : 'Выбранный час'
  const delta = index > 0 ? hour.power_norm - result.hours[index - 1].power_norm : 0
  if (intent === 'ramp' && delta >= 0) return 'В выбранном периоде нет почасового снижения мощности.'
  return `${name} · ${result.turbine_id}: ${dayLabel(hour.valid_at, result.timezone)}, ${hourLabel(hour.valid_at, result.timezone)} — ${percent(hour.power_norm)}. Ветер ${decimal(hour.wind_speed_ms)} м/с.${intent === 'ramp' ? ` Изменение за час: ${signedPoints(delta)}.` : ''}`
}

export function biggestDrop(result: ForecastResult): { index: number, delta: number } | null {
  const index = selectForecastHour(result, 'ramp')
  if (index === null || index === 0) return null
  const delta = result.hours[index].power_norm - result.hours[index - 1].power_norm
  return delta <= -.05 ? { index, delta } : null
}
