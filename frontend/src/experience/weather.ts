import type { ForecastHour, Site, WeatherMode } from '../types'
import type { NormalizedWeatherState } from './types'

const TAU = Math.PI * 2
const radians = Math.PI / 180
export const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
export const smoothstep = (min: number, max: number, value: number) => {
  const t = clamp((value - min) / (max - min), 0, 1)
  return t * t * (3 - 2 * t)
}

/** NOAA fractional-year solar equations. This is derived illumination, not a weather observation.
 * https://gml.noaa.gov/grad/solcalc/solareqns.PDF. No atmospheric refraction correction. */
export function solarPosition(timestamp: string, latitude: number, longitude: number) {
  const date = new Date(timestamp)
  if (!Number.isFinite(date.getTime()) || !Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    throw new Error('Для положения солнца нужны корректные время и координаты.')
  }
  const year = date.getUTCFullYear()
  const yearLength = (Date.UTC(year + 1, 0, 1) - Date.UTC(year, 0, 1)) / 86400000
  const day = Math.floor((date.getTime() - Date.UTC(year, 0, 1)) / 86400000) + 1
  const hour = date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600
  const gamma = TAU / yearLength * (day - 1 + (hour - 12) / 24)
  const equation = 229.18 * (0.000075 + 0.001868 * Math.cos(gamma) - 0.032077 * Math.sin(gamma)
    - 0.014615 * Math.cos(2 * gamma) - 0.040849 * Math.sin(2 * gamma))
  const declination = 0.006918 - 0.399912 * Math.cos(gamma) + 0.070257 * Math.sin(gamma)
    - 0.006758 * Math.cos(2 * gamma) + 0.000907 * Math.sin(2 * gamma)
    - 0.002697 * Math.cos(3 * gamma) + 0.00148 * Math.sin(3 * gamma)
  const solarMinutes = ((hour * 60 + equation + 4 * longitude) % 1440 + 1440) % 1440
  const hourAngle = (solarMinutes / 4 - 180) * radians
  const lat = latitude * radians
  const altitude = Math.asin(clamp(Math.sin(lat) * Math.sin(declination)
    + Math.cos(lat) * Math.cos(declination) * Math.cos(hourAngle), -1, 1))
  const azimuth = (Math.atan2(Math.sin(hourAngle), Math.cos(hourAngle) * Math.sin(lat)
    - Math.tan(declination) * Math.cos(lat)) + Math.PI + TAU) % TAU
  return { altitude, azimuth }
}

/** Visual rad/s, not operational telemetry or a power model. 0 below cut-in, capped at 14 rpm. */
export function windSpeedToRotorSpeed(windSpeed: number | null | undefined, rotorRPM?: number | null) {
  if (rotorRPM != null && Number.isFinite(rotorRPM)) return clamp(rotorRPM, 0, 24) * TAU / 60
  if (windSpeed == null || !Number.isFinite(windSpeed)) return 0
  const normalized = smoothstep(2, 16, windSpeed)
  return clamp(Math.pow(normalized, 0.72) * 14 * TAU / 60, 0, 14 * TAU / 60)
}

/** The HTTP seam currently supplies wind and temperature only. Do not infer the other fields. */
export function weatherForHour(
  hour: ForecastHour | null,
  site: Site,
  timestamp?: string,
  source: WeatherMode = 'fixture',
): NormalizedWeatherState | null {
  const at = timestamp ?? hour?.valid_at
  if (!at) return null
  return {
    timestamp: at,
    temperature: hour && Number.isFinite(hour.temperature_c) ? hour.temperature_c : null,
    windSpeed: hour && Number.isFinite(hour.wind_speed_ms) && hour.wind_speed_ms >= 0 ? hour.wind_speed_ms : null,
    windDirection: null, cloudCover: null, precipitation: null, humidity: null,
    visibility: null, weatherCode: null, rotorRPM: null,
    sunPosition: solarPosition(at, site.latitude, site.longitude),
    source: hour ? source : 'unavailable',
  }
}

export interface VisualWeather {
  sunAltitude: number; sunAzimuth: number; rotorSpeed: number; windSpeed: number
  windDirection: number; cloudCover: number; precipitation: number; visibility: number
}

const neutralVisual = (): VisualWeather => ({
  sunAltitude: 0.52, sunAzimuth: 4.1, rotorSpeed: 0, windSpeed: 0,
  windDirection: 0, cloudCover: 0, precipitation: 0, visibility: 50000,
})

/** Persistent imperative interpolation; visual defaults never flow back into data/UI. */
export class WeatherInterpolator {
  readonly currentVisualState = neutralVisual()
  private targetVisualState = neutralVisual()

  setTarget(weather: NormalizedWeatherState | null) {
    this.targetVisualState = weather ? {
      sunAltitude: weather.sunPosition.altitude,
      sunAzimuth: weather.sunPosition.azimuth,
      rotorSpeed: windSpeedToRotorSpeed(weather.windSpeed, weather.rotorRPM),
      windSpeed: weather.windSpeed ?? 0,
      windDirection: (weather.windDirection ?? 0) * radians,
      cloudCover: weather.cloudCover == null ? 0 : clamp(weather.cloudCover, 0, 1),
      precipitation: Math.max(0, weather.precipitation ?? 0),
      visibility: Math.max(100, weather.visibility ?? 50000),
    } : neutralVisual()
  }

  update(delta: number, reducedMotion = false) {
    const current = this.currentVisualState
    const target = this.targetVisualState
    const dt = clamp(delta, 0, 0.05)
    for (const key of Object.keys(current) as (keyof VisualWeather)[]) {
      let difference = target[key] - current[key]
      if (key === 'sunAzimuth' || key === 'windDirection') difference = Math.atan2(Math.sin(difference), Math.cos(difference))
      const rate = key === 'rotorSpeed' ? (difference > 0 ? 0.8 : 0.55) : reducedMotion ? 12 : 5.5
      current[key] += difference * (1 - Math.exp(-rate * dt))
    }
    return current
  }
}
