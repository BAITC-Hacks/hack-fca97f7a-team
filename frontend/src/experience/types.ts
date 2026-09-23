import type { WeatherMode } from '../types'

/** Provider-independent weather. Null means not supplied, never a fair-weather claim. */
export interface NormalizedWeatherState {
  timestamp: string
  temperature: number | null // °C
  windSpeed: number | null // m/s
  windDirection: number | null // degrees clockwise from north, meteorological
  cloudCover: number | null // 0–1
  precipitation: number | null // mm/h
  humidity: number | null // 0–1
  visibility: number | null // metres
  weatherCode: number | null
  sunPosition: { altitude: number; azimuth: number } // radians, azimuth clockwise from north
  rotorRPM?: number | null
  source: WeatherMode | 'unavailable'
}

export type SceneQuality = 'auto' | 'high' | 'medium' | 'low'
