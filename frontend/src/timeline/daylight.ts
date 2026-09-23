import type { ForecastResult, Site } from '../types'
import { solarPosition } from '../experience/weather.ts'

/** A shortcut to an existing forecast row, never a lighting override or invented time. */
export function daylightHour(result: ForecastResult, site: Site, selectedIndex: number): number | null {
  const selected = result.hours[selectedIndex]
  if (!selected || solarPosition(selected.valid_at, site.latitude, site.longitude).altitude >= 0) return null
  const date = new Intl.DateTimeFormat('en-CA', { timeZone: result.timezone, year: 'numeric', month: '2-digit', day: '2-digit' })
  const day = (timestamp: string) => date.format(new Date(timestamp))
  const candidates = result.hours.map((hour, index) => ({ index, day: day(hour.valid_at), altitude: solarPosition(hour.valid_at, site.latitude, site.longitude).altitude })).filter(hour => hour.altitude > .08)
  if (!candidates.length) return null
  const sameDay = candidates.filter(hour => hour.day === day(selected.valid_at))
  const closest = candidates.reduce((best, hour) => Math.abs(hour.index - selectedIndex) < Math.abs(best.index - selectedIndex) ? hour : best)
  const available = sameDay.length ? sameDay : candidates.filter(hour => hour.day === closest.day)
  return available.reduce((best, hour) => hour.altitude > best.altitude ? hour : best).index
}
