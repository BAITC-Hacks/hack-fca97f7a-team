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

export interface ReplayForecastRequest {
  turbine_id: string
  forecast_date: string
  horizon_hours: 24 | 48
  weather_source: 'verified' | 'provider-documented'
}

export interface ForecastHour {
  valid_at: string
  lead_hour: number
  wind_speed_ms: number
  temperature_c: number
  power_norm: number
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

export interface WeatherProvenance {
  provenance_status: string
  provider?: string
  retrieved_at?: string | null
  weather_cache_hit?: boolean
  [key: string]: string | number | boolean | null | undefined
}

export interface ModelProvenance {
  profile: string
  training_weather_kind: string
  forecast_accuracy_verified: boolean
  weather_model: string
  wind_height_m: number
}

export interface ForecastResult extends ForecastRequest {
  origin: string
  status: 'ok'
  forecast_id: string
  model_input: ModelInput
  timezone: string
  run_id: string
  model_id: string
  fingerprint: string
  cache_hit: boolean
  train_last_interval_start: string
  weather_provenance: WeatherProvenance
  model_provenance?: ModelProvenance
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
  notes?: string[]
}

export interface TimeSelection {
  start: string
  end: string
}

export interface ToolResult {
  tool: string
  data: Record<string, unknown>
  text: string
  selection?: TimeSelection | null
  table?: { columns: string[], rows: string[][] }
}

export interface QuestionAnswer extends Explanation {
  conversation_id: string
  selection?: TimeSelection | null
  tool_results?: ToolResult[]
}
