export type Agent = 'Human' | 'AI-assisted' | 'Copilot' | 'Claude 3.5 Sonnet' | 'GPT-4o' | 'Unknown'
export type Complexity = 'L1' | 'L2' | 'L3' | 'L4' | 'Unknown'
export type PrEvent = {
  id: string; number: number; title: string; author: string; url: string; agent: Agent
  additions: number; deletions: number; ci: string; review: string; complexity: Complexity
  latency: number | null; coverage: number | null; promptTokens: number | null
  completionTokens: number | null; cost: number | null; minutes: number | null
  rollback: boolean; createdAt: number; mergedAt: number | null; state: string
  labels: string[]; runs: Array<{ status: string; conclusion: string | null; run_attempt: number }>
}

export type TelemetryMetrics = {
  repository: string; totalPullRequests: number; mergedPullRequests: number
  openPullRequests: number; aiAssistedPullRequests: number; humanPullRequests: number
  unknownAttribution: number; aiAverageMergeMinutes: number | null
  humanAverageMergeMinutes: number | null; ciRuns: number; ciPassRate: number | null
  tokenRecords: number; tokenCost: number; promptTokens: number
  completionTokens: number; lastSync: string | null
  modelUsageRecords: number
  modelUsagePromptTokens: number
  modelUsageCompletionTokens: number
  cursorActivityRecords: number
}

export type ServiceHealth = {
  ok: boolean
  repository: string
  webhookConfigured: boolean
  tokenIngestConfigured: boolean
  lastSync: string | null
}

export type ModelUsageEvent = {
  id: number
  repository: string | null
  pullRequestNumber: number | null
  provider: string
  client: string
  model: string
  promptTokens: number
  completionTokens: number
  latencyMs: number | null
  createdAt: string
}

export type CursorActivityEvent = {
  id: number
  repository: string | null
  source: string
  model: string | null
  editsCount: number
  changedChars: number
  createdAt: string
}
