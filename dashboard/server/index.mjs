import { createHmac, timingSafeEqual } from 'node:crypto'
import { createReadStream, existsSync, mkdirSync } from 'node:fs'
import { readFile, stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { DatabaseSync } from 'node:sqlite'

const root = resolve(import.meta.dirname, '..')
let repo = process.env.GITHUB_REPOSITORY || 'Nob1taaaa/LocalAIAgentWithRAG-Assistant'
const databaseFile = resolve(process.env.DATABASE_PATH || resolve(root, 'data/assist-ledger.sqlite'))
const port = Number(process.env.PORT || 3000)
const host = process.env.HOST || '127.0.0.1'
mkdirSync(resolve(databaseFile, '..'), { recursive: true })
const db = new DatabaseSync(databaseFile)
db.exec(`
  pragma journal_mode = WAL;
  create table if not exists pull_requests (
    number integer primary key, title text not null, author text not null,
    html_url text not null, state text not null, draft integer not null default 0,
    created_at text not null, updated_at text not null, merged_at text,
    additions integer not null default 0, deletions integer not null default 0,
    changed_files integer not null default 0, labels text not null default '[]',
    agent text not null default 'Unknown', complexity text not null default 'Unknown',
    ci_status text not null default 'Unknown', review_status text not null default 'Unknown'
  );
  create table if not exists ci_runs (
    id integer primary key, pull_request_number integer not null, name text not null,
    status text not null, conclusion text, run_attempt integer not null default 1,
    created_at text, updated_at text
  );
  create table if not exists token_telemetry (
    id integer primary key, pull_request_number integer not null, model text not null,
    prompt_tokens integer, completion_tokens integer, estimated_cost real,
    latency_ms integer, created_at text not null default current_timestamp
  );
  create table if not exists app_state (key text primary key, value text not null);
  create table if not exists model_usage (
    id integer primary key autoincrement,
    repository text,
    pull_request_number integer,
    provider text not null default 'ollama',
    client text not null,
    model text not null,
    prompt_tokens integer not null default 0,
    completion_tokens integer not null default 0,
    latency_ms integer,
    created_at text not null default current_timestamp
  );
  create table if not exists cursor_activity (
    id integer primary key autoincrement,
    repository text,
    source text not null,
    model text,
    edits_count integer not null default 0,
    changed_chars integer not null default 0,
    created_at text not null default current_timestamp
  );
`)

const upsertPr = db.prepare(`insert into pull_requests
  (number,title,author,html_url,state,draft,created_at,updated_at,merged_at,additions,deletions,changed_files,labels,agent,complexity,ci_status,review_status)
  values (@number,@title,@author,@html_url,@state,@draft,@created_at,@updated_at,@merged_at,@additions,@deletions,@changed_files,@labels,@agent,@complexity,@ci_status,@review_status)
  on conflict(number) do update set title=excluded.title, author=excluded.author, html_url=excluded.html_url,
  state=excluded.state,draft=excluded.draft,updated_at=excluded.updated_at,merged_at=excluded.merged_at,
  additions=excluded.additions,deletions=excluded.deletions,changed_files=excluded.changed_files,
  labels=excluded.labels,agent=excluded.agent,complexity=excluded.complexity,
  review_status=case when excluded.review_status in ('Merged','Closed','Draft') then excluded.review_status
    when pull_requests.review_status='Unknown' then excluded.review_status else pull_requests.review_status end`)
const upsertRun = db.prepare(`insert into ci_runs (id,pull_request_number,name,status,conclusion,run_attempt,created_at,updated_at)
  values (@id,@pull_request_number,@name,@status,@conclusion,@run_attempt,@created_at,@updated_at)
  on conflict(id) do update set status=excluded.status,conclusion=excluded.conclusion,run_attempt=excluded.run_attempt,updated_at=excluded.updated_at`)

function classify(labels = []) {
  const normalized = labels.map((label) => (typeof label === 'string' ? label : label.name || '').toLowerCase())
  const tag = normalized.find((label) => label.startsWith('assist-ledger:') || label.startsWith('ai:')) || ''
  const value = tag.split(':')[1]?.replaceAll('_', ' ').trim()
  const known = {
    human: 'Human',
    'human-only': 'Human',
    'ai-assisted': 'AI-assisted',
    copilot: 'Copilot',
    claude: 'Claude 3.5 Sonnet',
    'claude 3.5 sonnet': 'Claude 3.5 Sonnet',
    'gpt-4o': 'GPT-4o',
    'gpt 4o': 'GPT-4o',
  }
  const agent = known[value] || 'Unknown'
  const level = normalized.find((label) => /^l[1-4]$/.test(label))?.toUpperCase() || 'Unknown'
  return { agent, complexity: level }
}

function prRecord(pr) {
  const labels = (pr.labels || []).map((label) => typeof label === 'string' ? label : label.name)
  const { agent, complexity } = classify(labels)
  return {
    number: pr.number, title: pr.title || '(untitled)', author: pr.user?.login || 'unknown',
    html_url: pr.html_url || '', state: pr.state || 'open', draft: pr.draft ? 1 : 0,
    created_at: pr.created_at || new Date().toISOString(), updated_at: pr.updated_at || new Date().toISOString(),
    merged_at: pr.merged_at || null, additions: pr.additions || 0, deletions: pr.deletions || 0,
    changed_files: pr.changed_files || 0, labels: JSON.stringify(labels), agent, complexity,
    ci_status: pr.ci_status || 'Unknown', review_status: pr.review_status || (pr.merged_at ? 'Merged' : pr.state === 'closed' ? 'Closed' : pr.draft ? 'Draft' : 'Open'),
  }
}

function savePr(pr) { upsertPr.run(prRecord(pr)) }

function signatureIsValid(raw, signature) {
  const secret = process.env.GITHUB_WEBHOOK_SECRET
  if (!secret || !signature?.startsWith('sha256=')) return false
  const expected = Buffer.from(`sha256=${createHmac('sha256', secret).update(raw).digest('hex')}`)
  const received = Buffer.from(signature)
  return expected.length === received.length && timingSafeEqual(expected, received)
}

function json(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  res.end(JSON.stringify(body))
}

async function bodyBuffer(req, limit = 2_000_000) {
  const chunks = []; let size = 0
  for await (const chunk of req) { size += chunk.length; if (size > limit) throw new Error('Request body too large'); chunks.push(chunk) }
  return Buffer.concat(chunks)
}

async function github(path) {
  const headers = { accept: 'application/vnd.github+json', 'x-github-api-version': '2022-11-28', 'user-agent': 'assist-ledger' }
  if (process.env.GITHUB_TOKEN) headers.authorization = `Bearer ${process.env.GITHUB_TOKEN}`
  const response = await fetch(`https://api.github.com${path}`, { headers })
  if (!response.ok) throw new Error(`GitHub API returned ${response.status}: ${(await response.text()).slice(0, 300)}`)
  return response.json()
}

async function githubPages(path) {
  const records = []
  for (let page = 1; page <= 10; page++) {
    const separator = path.includes('?') ? '&' : '?'
    const batch = await github(`${path}${separator}page=${page}`)
    const items = Array.isArray(batch) ? batch : batch.workflow_runs || []
    records.push(...items)
    if (items.length < 100) break
  }
  return records
}

let syncPromise = null
async function syncGithub() {
  if (syncPromise) return syncPromise
  syncPromise = (async () => {
    const [pulls, workflowRuns] = await Promise.all([
      githubPages(`/repos/${repo}/pulls?state=all&per_page=100&sort=created&direction=desc`),
      githubPages(`/repos/${repo}/actions/runs?per_page=100`),
    ])
    db.exec('begin')
    try {
      for (const pr of pulls) {
        const linkedRuns = workflowRuns.filter((run) => (run.pull_requests || []).some((linked) => linked.number === pr.number))
        const latest = linkedRuns.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))[0]
        const reviews = []
        // PR list endpoint omits review state; labels remain the explicit attribution mechanism.
        savePr({ ...pr, ci_status: latest?.status === 'completed' ? (latest.conclusion === 'success' ? 'Passed' : latest.conclusion === 'failure' ? 'Failed' : 'Unknown') : latest ? 'Running' : 'Unknown', review_status: pr.merged_at ? 'Merged' : pr.state === 'closed' ? 'Closed' : pr.draft ? 'Draft' : 'Open' })
        for (const run of linkedRuns) {
          for (const linked of run.pull_requests || []) if (linked.number === pr.number) {
            upsertRun.run({ id: run.id, pull_request_number: pr.number, name: run.name || 'GitHub Actions', status: run.status || 'unknown', conclusion: run.conclusion, run_attempt: run.run_attempt || 1, created_at: run.created_at, updated_at: run.updated_at })
            break
          }
        }
      }
      db.exec('commit')
    } catch (error) { db.exec('rollback'); throw error }
    const synced = new Date().toISOString()
    db.prepare('insert into app_state(key,value) values(?,?) on conflict(key) do update set value=excluded.value').run('last_sync', synced)
    return { repository: repo, pullRequests: pulls.length, workflowRuns: workflowRuns.length, syncedAt: synced }
  })().finally(() => { syncPromise = null })
  return syncPromise
}

function fromDb(row) {
  const minutes = row.merged_at ? Math.max(0, Math.round((Date.parse(row.merged_at) - Date.parse(row.created_at)) / 60_000)) : null
  const ci = db.prepare('select status, conclusion, run_attempt from ci_runs where pull_request_number=? order by updated_at desc').all(row.number)
  const tokens = db.prepare('select model,prompt_tokens,completion_tokens,estimated_cost,latency_ms from token_telemetry where pull_request_number=? order by created_at desc limit 1').get(row.number)
  return {
    id: `#${row.number}`, number: row.number, title: row.title, author: row.author, url: row.html_url,
    agent: row.agent, additions: row.additions, deletions: row.deletions, ci: row.ci_status,
    review: row.review_status, complexity: row.complexity, latency: tokens?.latency_ms == null ? null : tokens.latency_ms / 1000,
    coverage: null, promptTokens: tokens?.prompt_tokens ?? null, completionTokens: tokens?.completion_tokens ?? null,
    cost: tokens?.estimated_cost ?? null, minutes, rollback: false, createdAt: Date.parse(row.created_at),
    state: row.state, mergedAt: row.merged_at ? Date.parse(row.merged_at) : null,
    labels: JSON.parse(row.labels), runs: ci,
  }
}

function metrics() {
  const rows = db.prepare('select * from pull_requests').all()
  const merged = rows.filter((row) => row.merged_at)
  const aiMerged = merged.filter((row) => row.agent !== 'Human' && row.agent !== 'Unknown')
  const humanMerged = merged.filter((row) => row.agent === 'Human')
  const avg = (items) => items.length ? Math.round(items.reduce((sum, row) => sum + (Date.parse(row.merged_at) - Date.parse(row.created_at)) / 60_000, 0) / items.length) : null
  const runs = db.prepare("select pull_request_number, max(case when conclusion='success' then 1 else 0 end) as passed, count(*) as total from ci_runs where status='completed' group by pull_request_number").all()
  const telemetry = db.prepare('select count(*) as count, coalesce(sum(estimated_cost),0) as cost, coalesce(sum(prompt_tokens),0) as prompt, coalesce(sum(completion_tokens),0) as completion from token_telemetry').get()
  const modelUsage = db.prepare('select count(*) as count, coalesce(sum(prompt_tokens),0) as prompt, coalesce(sum(completion_tokens),0) as completion from model_usage').get()
  const cursorActivity = db.prepare('select count(*) as count from cursor_activity').get()
  return {
    repository: repo, totalPullRequests: rows.length, mergedPullRequests: merged.length,
    openPullRequests: rows.filter((row) => row.state === 'open').length,
    aiAssistedPullRequests: rows.filter((row) => row.agent !== 'Human' && row.agent !== 'Unknown').length,
    humanPullRequests: rows.filter((row) => row.agent === 'Human').length,
    unknownAttribution: rows.filter((row) => row.agent === 'Unknown').length,
    aiAverageMergeMinutes: avg(aiMerged), humanAverageMergeMinutes: avg(humanMerged),
    ciRuns: runs.length, ciPassRate: runs.length ? Math.round(runs.filter((run) => run.passed).length / runs.length * 1000) / 10 : null,
    tokenRecords: telemetry.count, tokenCost: Number(telemetry.cost), promptTokens: Number(telemetry.prompt), completionTokens: Number(telemetry.completion),
    modelUsageRecords: modelUsage.count,
    modelUsagePromptTokens: Number(modelUsage.prompt),
    modelUsageCompletionTokens: Number(modelUsage.completion),
    cursorActivityRecords: cursorActivity.count,
    lastSync: db.prepare("select value from app_state where key='last_sync'").get()?.value || null,
  }
}

function ingestKeyIsValid(receivedKey) {
  const configuredKey = process.env.ASSIST_LEDGER_INGEST_KEY
  if (!configuredKey || typeof receivedKey !== 'string') return false
  const expected = Buffer.from(configuredKey)
  const actual = Buffer.from(receivedKey)
  return expected.length === actual.length && timingSafeEqual(expected, actual)
}

function mapModelUsageRow(row) {
  return {
    id: row.id,
    repository: row.repository,
    pullRequestNumber: row.pull_request_number,
    provider: row.provider,
    client: row.client,
    model: row.model,
    promptTokens: row.prompt_tokens,
    completionTokens: row.completion_tokens,
    latencyMs: row.latency_ms,
    createdAt: row.created_at,
  }
}

function mapCursorActivityRow(row) {
  return {
    id: row.id,
    repository: row.repository,
    source: row.source,
    model: row.model,
    editsCount: row.edits_count,
    changedChars: row.changed_chars,
    createdAt: row.created_at,
  }
}

async function serveStatic(req, res) {
  const requestPath = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
  const requested = requestPath === '/' ? '/index.html' : requestPath
  const webRoot = resolve(root, 'dist')
  const file = resolve(webRoot, `.${requested}`)
  if (!(file === webRoot || file.startsWith(webRoot + sep)) || !existsSync(file)) {
    const fallback = resolve(webRoot, 'index.html')
    if (!existsSync(fallback)) return json(res, 404, { error: 'Frontend is not built. Run npm run build.' })
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); res.end(await readFile(fallback)); return
  }
  if (!(await stat(file)).isFile()) return json(res, 404, { error: 'Not found' })
  const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon' }
  res.writeHead(200, { 'content-type': types[extname(file)] || 'application/octet-stream' })
  createReadStream(file).pipe(res)
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`)
    if (req.method === 'GET' && url.pathname === '/api/health') return json(res, 200, { ok: true, repository: repo, webhookConfigured: Boolean(process.env.GITHUB_WEBHOOK_SECRET), tokenIngestConfigured: Boolean(process.env.ASSIST_LEDGER_INGEST_KEY), lastSync: metrics().lastSync })
    if (req.method === 'GET' && url.pathname === '/api/pull-requests') {
      const rows = db.prepare('select * from pull_requests order by created_at desc limit 500').all()
      return json(res, 200, rows.map(fromDb))
    }
    if (req.method === 'GET' && url.pathname === '/api/metrics') return json(res, 200, metrics())
    if (req.method === 'POST' && url.pathname === '/api/sync') {
      try { return json(res, 200, await syncGithub()) }
      catch (error) { return json(res, 502, { error: error.message }) }
    }
    if (req.method === 'GET' && url.pathname === '/api/telemetry/model-usage') {
      const limit = Math.min(200, Math.max(1, Number(url.searchParams.get('limit') || 50)))
      const rows = db.prepare('select * from model_usage order by created_at desc limit ?').all(limit)
      return json(res, 200, rows.map(mapModelUsageRow))
    }
    if (req.method === 'GET' && url.pathname === '/api/telemetry/cursor-activity') {
      const limit = Math.min(200, Math.max(1, Number(url.searchParams.get('limit') || 30)))
      const rows = db.prepare('select * from cursor_activity order by created_at desc limit ?').all(limit)
      return json(res, 200, rows.map(mapCursorActivityRow))
    }
    if (req.method === 'POST' && url.pathname === '/api/telemetry/model-usage') {
      if (!ingestKeyIsValid(req.headers['x-assist-ledger-key'])) {
        return json(res, 401, { error: 'Model usage ingestion is not configured or key is invalid' })
      }
      const payload = JSON.parse((await bodyBuffer(req, 64_000)).toString('utf8'))
      if (!payload.model || !payload.client) return json(res, 400, { error: 'model and client are required' })
      const validInt = (value) => value == null ? 0 : Number.isInteger(Number(value)) && Number(value) >= 0 ? Number(value) : null
      const prompt = validInt(payload.prompt_tokens ?? payload.promptTokens)
      const completion = validInt(payload.completion_tokens ?? payload.completionTokens)
      const latency = validInt(payload.latency_ms ?? payload.latencyMs)
      if (prompt == null || completion == null || (latency != null && latency < 0)) {
        return json(res, 400, { error: 'token counts must be non-negative integers' })
      }
      const prNumber = payload.pull_request_number ?? payload.pullRequestNumber
      const pullRequestNumber = prNumber == null ? null : Number(prNumber)
      if (pullRequestNumber != null && (!Number.isInteger(pullRequestNumber) || pullRequestNumber < 1)) {
        return json(res, 400, { error: 'pull_request_number must be a positive integer when provided' })
      }
      db.prepare(`insert into model_usage (repository,pull_request_number,provider,client,model,prompt_tokens,completion_tokens,latency_ms)
        values (?,?,?,?,?,?,?,?)`).run(
        payload.repository ? String(payload.repository).slice(0, 200) : repo,
        pullRequestNumber,
        String(payload.provider || 'ollama').slice(0, 40),
        String(payload.client).slice(0, 80),
        String(payload.model).slice(0, 120),
        prompt,
        completion,
        latency,
      )
      return json(res, 201, { accepted: true })
    }
    if (req.method === 'POST' && url.pathname === '/api/telemetry/cursor-activity') {
      if (!ingestKeyIsValid(req.headers['x-assist-ledger-key'])) {
        return json(res, 401, { error: 'Cursor activity ingestion is not configured or key is invalid' })
      }
      const payload = JSON.parse((await bodyBuffer(req, 64_000)).toString('utf8'))
      if (!payload.source) return json(res, 400, { error: 'source is required' })
      const validInt = (value) => value == null ? 0 : Number.isInteger(Number(value)) && Number(value) >= 0 ? Number(value) : null
      const edits = validInt(payload.edits_count ?? payload.editsCount)
      const chars = validInt(payload.changed_chars ?? payload.changedChars)
      if (edits == null || chars == null) return json(res, 400, { error: 'edits_count and changed_chars must be non-negative integers' })
      db.prepare(`insert into cursor_activity (repository,source,model,edits_count,changed_chars)
        values (?,?,?,?,?)`).run(
        payload.repository ? String(payload.repository).slice(0, 200) : repo,
        String(payload.source).slice(0, 40),
        payload.model ? String(payload.model).slice(0, 120) : null,
        edits,
        chars,
      )
      return json(res, 201, { accepted: true })
    }
    if (req.method === 'POST' && url.pathname === '/api/telemetry/tokens') {
      if (!ingestKeyIsValid(req.headers['x-assist-ledger-key'])) return json(res, 401, { error: 'Token ingestion is not configured or key is missing' })
      const payload = JSON.parse((await bodyBuffer(req, 64_000)).toString('utf8'))
      const number = Number(payload.pullRequestNumber)
      if (!Number.isInteger(number) || number < 1 || !payload.model) return json(res, 400, { error: 'pullRequestNumber and model are required' })
      const validInt = (value) => value == null ? null : Number.isInteger(Number(value)) && Number(value) >= 0 ? Number(value) : null
      const cost = payload.estimatedCost == null ? null : Number(payload.estimatedCost)
      if (cost != null && (!Number.isFinite(cost) || cost < 0)) return json(res, 400, { error: 'estimatedCost must be a non-negative number' })
      db.prepare(`insert into token_telemetry (pull_request_number,model,prompt_tokens,completion_tokens,estimated_cost,latency_ms)
        values (?,?,?,?,?,?)`).run(number, String(payload.model).slice(0, 120), validInt(payload.promptTokens), validInt(payload.completionTokens), cost, validInt(payload.latencyMs))
      return json(res, 201, { accepted: true, pullRequestNumber: number })
    }
    if (req.method === 'POST' && url.pathname === '/api/webhooks/github') {
      const raw = await bodyBuffer(req)
      if (!signatureIsValid(raw, req.headers['x-hub-signature-256'])) return json(res, 401, { error: 'Invalid or missing webhook signature' })
      const event = req.headers['x-github-event']
      const payload = JSON.parse(raw.toString('utf8'))
      if (payload.repository?.full_name && payload.repository.full_name.toLowerCase() !== repo.toLowerCase()) return json(res, 202, { ignored: true, reason: 'Repository does not match configured repository' })
      if (event === 'pull_request' && payload.pull_request) {
        savePr(payload.pull_request)
        const action = payload.action || 'updated'
        return json(res, 202, { accepted: true, event, action, number: payload.pull_request.number })
      }
      if (event === 'pull_request_review' && payload.pull_request && payload.review) {
        const state = String(payload.review.state || '').toLowerCase()
        const review = state === 'approved' ? 'Approved' : state === 'changes_requested' ? 'Changes requested' : 'In review'
        savePr(payload.pull_request)
        db.prepare('update pull_requests set review_status=? where number=?').run(review, payload.pull_request.number)
        return json(res, 202, { accepted: true, event, number: payload.pull_request.number, review })
      }
      if (event === 'workflow_run' && payload.workflow_run) {
        const run = payload.workflow_run
        for (const pr of run.pull_requests || []) {
          upsertRun.run({ id: run.id, pull_request_number: pr.number, name: run.name || 'GitHub Actions', status: run.status || 'unknown', conclusion: run.conclusion, run_attempt: run.run_attempt || 1, created_at: run.created_at, updated_at: run.updated_at })
          const ci = run.status === 'completed' ? (run.conclusion === 'success' ? 'Passed' : run.conclusion === 'failure' ? 'Failed' : 'Unknown') : 'Running'
          db.prepare('update pull_requests set ci_status=? where number=?').run(ci, pr.number)
        }
        return json(res, 202, { accepted: true, event, pullRequests: (run.pull_requests || []).length })
      }
      return json(res, 202, { accepted: true, ignored: true, event })
    }
    if (req.method === 'GET') return serveStatic(req, res)
    return json(res, 404, { error: 'Not found' })
  } catch (error) { return json(res, 500, { error: error.message || 'Internal server error' }) }
})

server.listen(port, host, () => console.log(`Assist Ledger API for ${repo} listening on http://${host}:${port}`))
process.on('SIGINT', () => { server.close(() => { db.close(); process.exit(0) }) })
process.on('SIGTERM', () => { server.close(() => { db.close(); process.exit(0) }) })
