import type { ApiError, Explanation, ForecastRequest, ForecastResult, Site, WeatherMode } from './types'

export class ApiFailure extends Error {
  code: string
  trace: ApiError['trace']

  constructor(error: ApiError) {
    super(error.message)
    this.name = 'ApiFailure'
    this.code = error.code
    this.trace = error.trace
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, options)
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new Error(`Сервер вернул ответ ${response.status} без JSON.`)
  }
  if (!response.ok || (body && typeof body === 'object' && 'status' in body && body.status === 'error')) {
    const error = body as ApiError
    throw new ApiFailure({ status: 'error', code: error.code || 'REQUEST_FAILED', message: error.message || `Запрос не выполнен (${response.status}).`, trace: error.trace })
  }
  return body as T
}

const jsonHeaders = { 'Content-Type': 'application/json' }

export function getSites(mode: WeatherMode, signal?: AbortSignal): Promise<Site[]> {
  return request<{ sites: Site[] }>(`/sites?mode=${encodeURIComponent(mode)}`, { signal }).then((body) => body.sites)
}

export function createForecast(input: ForecastRequest, signal?: AbortSignal): Promise<ForecastResult> {
  return request<ForecastResult>('/forecasts', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(input), signal })
}

export function explainForecast(id: string, signal?: AbortSignal): Promise<Explanation> {
  return request<Explanation>(`/forecasts/${encodeURIComponent(id)}/explanation`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ backend: 'llm' }), signal })
}

export function askQuestion(id: string, question: string, signal?: AbortSignal): Promise<Explanation> {
  return request<Explanation>(`/forecasts/${encodeURIComponent(id)}/questions`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ question, backend: 'llm' }), signal })
}

export function downloadUrl(id: string, kind: 'forecast' | 'model-input'): string {
  return `/api/forecasts/${encodeURIComponent(id)}/download?kind=${kind}`
}
