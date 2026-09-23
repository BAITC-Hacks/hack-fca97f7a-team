export type WeatherMode = 'fixture' | 'archive' | 'live'

export interface Site {
  turbine_id: string
  latitude: number
  longitude: number
  timezone: string
  coordinate_status: string
  coordinate_source?: string
}

export interface ForecastRequest {
  turbine_id: string
  origin: string
  horizon_hours: 24 | 48
  mode: WeatherMode
}

export interface ForecastHour {
  valid_at: string
  lead_hour: number
  wind_speed_ms: number
  temperature_c: number
  power_norm: number
  baseline_norm: number
}

export interface ModelInput {
  schema_version: 'weather-features-v1'
  filename: string
  sha256: string
  row_count: number
  columns: string[]
}

export interface TraceStep {
  step: string
  status: string
  detail: string
}

export interface ForecastResult extends ForecastRequest {
  status: 'ok'
  forecast_id: string
  model_input: ModelInput
  timezone: string
  run_id: string
  model_id: string
  fingerprint: string
  cache_hit: boolean
  train_last_interval_start: string
  weather_provenance: Record<string, string>
  hours: ForecastHour[]
  analysis: {
    peak_power_norm: number
    peak_at: string
    min_power_norm: number
    min_at: string
    clipped_count: number
    warnings: string[]
  }
  trace: TraceStep[]
}

export interface ApiError {
  status: 'error'
  code: string
  message: string
  trace?: TraceStep[]
}

export interface Explanation {
  text: string
  backend: 'template' | 'llm'
  forecast_fingerprint: string
  warning: string | null
  model?: string
}
