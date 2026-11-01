import type { CursorActivityEvent, ModelUsageEvent, PrEvent, ServiceHealth, TelemetryMetrics } from '../sim/engine'

export interface TelemetryRepository {
  listPullRequests(): Promise<PrEvent[]>
  getMetrics(): Promise<TelemetryMetrics>
  getHealth(): Promise<ServiceHealth>
  listModelUsage(limit?: number): Promise<ModelUsageEvent[]>
  listCursorActivity(limit?: number): Promise<CursorActivityEvent[]>
  sync(): Promise<{ repository: string; pullRequests: number; workflowRuns: number; syncedAt: string }>
}

const apiBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${url}`, { ...init, headers: { accept: 'application/json', ...init?.headers } })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`)
  return body as T
}

export class ApiTelemetryRepository implements TelemetryRepository {
  listPullRequests() { return request<PrEvent[]>('/api/pull-requests') }
  getMetrics() { return request<TelemetryMetrics>('/api/metrics') }
  getHealth() { return request<ServiceHealth>('/api/health') }
  listModelUsage(limit = 50) { return request<ModelUsageEvent[]>(`/api/telemetry/model-usage?limit=${limit}`) }
  listCursorActivity(limit = 30) { return request<CursorActivityEvent[]>(`/api/telemetry/cursor-activity?limit=${limit}`) }
  sync() { return request<{ repository: string; pullRequests: number; workflowRuns: number; syncedAt: string }>('/api/sync', { method: 'POST' }) }
}

export const telemetryRepository: TelemetryRepository = new ApiTelemetryRepository()
