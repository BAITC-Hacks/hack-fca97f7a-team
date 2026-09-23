import type { ApiError, Explanation, ForecastRequest, ForecastResult, QuestionAnswer, Site } from './types'
import { apiErrors, ru } from './ru'

export class ApiFailure extends Error {
  code: string
  trace: ApiError['trace']

  constructor(error: ApiError) {
    super(apiErrors[error.code] || ru.requestFailed)
    this.name = 'ApiFailure'
    this.code = error.code
    this.trace = error.trace
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, options)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error(ru.networkError)
  }
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new Error(ru.invalidServerResponse)
  }
  if (!response.ok || (body && typeof body === 'object' && 'status' in body && body.status === 'error')) {
    const error = body as ApiError
    throw new ApiFailure({ status: 'error', code: error.code || 'REQUEST_FAILED', message: error.message || ru.requestFailed, trace: error.trace })
  }
  return body as T
}

const jsonHeaders = { 'Content-Type': 'application/json' }

export function getSites(mode: 'fixture' | 'archive' | 'live', signal?: AbortSignal): Promise<Site[]> {
  return request<{ sites: Site[] }>(`/sites?mode=${encodeURIComponent(mode)}`, { signal }).then((body) => body.sites)
}

export function createForecast(input: ForecastRequest, signal?: AbortSignal): Promise<ForecastResult> {
  return request<ForecastResult>('/forecasts', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(input), signal })
}

export function explainForecast(id: string, signal?: AbortSignal): Promise<Explanation> {
  return request<Explanation>(`/forecasts/${encodeURIComponent(id)}/explanation`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ backend: 'llm' }), signal })
}

export function askQuestion(id: string, question: string, conversationId?: string, signal?: AbortSignal): Promise<QuestionAnswer> {
  return request<QuestionAnswer>(`/forecasts/${encodeURIComponent(id)}/questions`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ question, backend: 'llm', ...(conversationId ? { conversation_id: conversationId } : {}) }), signal })
}

export function downloadUrl(id: string, kind: 'forecast' | 'model-input'): string {
  return `/api/forecasts/${encodeURIComponent(id)}/download?kind=${kind}`
}

export async function downloadCsv(id: string, kind: 'forecast' | 'model-input'): Promise<Blob> {
  let response: Response
  try {
    response = await fetch(downloadUrl(id, kind))
  } catch {
    throw new Error(ru.networkError)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as ApiError | null
    throw new ApiFailure({ status: 'error', code: body?.code || 'REQUEST_FAILED', message: body?.message || ru.requestFailed, trace: body?.trace })
  }
  return response.blob()
}
