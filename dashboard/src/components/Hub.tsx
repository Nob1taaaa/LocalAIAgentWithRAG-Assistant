import { useState } from 'react'
import { ArrowRight, BookOpen, Check, Copy, ShieldCheck } from 'lucide-react'

export default function Hub() {
  const [copied, setCopied] = useState('')
  const copy = async (id: string, text: string) => { await navigator.clipboard.writeText(text); setCopied(id); window.setTimeout(() => setCopied(''), 1800) }
  const setup = 'cp .env.example .env\n# set GITHUB_REPOSITORY=owner/name\nnpm run dev:full'
  const labels = 'assist-ledger:human-only\nassist-ledger:ai-assisted\nassist-ledger:copilot\nassist-ledger:claude\nassist-ledger:gpt-4o\nL1 · L2 · L3 · L4'
  const modelUsageCurl = `curl -X POST http://127.0.0.1:3000/api/telemetry/model-usage -H 'Content-Type: application/json' -H "X-Assist-Ledger-Key: $ASSIST_LEDGER_INGEST_KEY" -d '{"client":"python-rag","model":"llama3.2:3b","prompt_tokens":120,"completion_tokens":45,"latency_ms":900}'`
  const tokenCurl = `curl -X POST http://127.0.0.1:3000/api/telemetry/tokens -H 'Content-Type: application/json' -H "X-Assist-Ledger-Key: $ASSIST_LEDGER_INGEST_KEY" -d '{"pullRequestNumber":42,"model":"claude-3.5-sonnet","promptTokens":1200,"completionTokens":450,"estimatedCost":0.02,"latencyMs":9400}'`
  const tokenExample = 'X-Assist-Ledger-Key: <shared secret>\n{"pullRequestNumber":42,"model":"claude-3.5-sonnet","promptTokens":1200,"completionTokens":450,"estimatedCost":0.02,"latencyMs":9400}'
  const prPayload = `{
  "action": "opened",
  "number": 1842,
  "pull_request": { "title": "Example change", "additions": 142, "deletions": 38 },
  "repository": { "full_name": "owner/name" }
}`
  const ciPayload = `{
  "action": "completed",
  "workflow_run": {
    "id": 9123401,
    "name": "CI / Test suite",
    "status": "completed",
    "conclusion": "success",
    "pull_requests": [{ "number": 1842 }]
  },
  "repository": { "full_name": "owner/name" }
}`
  const hmac = `import { createHmac, timingSafeEqual } from 'node:crypto'
const expected = 'sha256=' + createHmac('sha256', secret)
  .update(rawBody).digest('hex')
const valid = timingSafeEqual(
  Buffer.from(signature), Buffer.from(expected)
)`
  const schema = `create table pull_requests (
  number integer primary key,
  title text not null,
  author text not null,
  state text not null,
  agent text not null default 'Unknown',
  complexity text not null default 'Unknown',
  additions integer not null default 0,
  deletions integer not null default 0,
  created_at text not null,
  merged_at text
);

create table ci_runs (
  id integer primary key,
  pull_request_number integer not null,
  name text not null,
  status text not null,
  conclusion text
);

create table token_telemetry (
  id integer primary key,
  pull_request_number integer not null,
  model text not null,
  prompt_tokens integer,
  completion_tokens integer,
  estimated_cost real,
  latency_ms integer
);`
  const CopyButton = ({ id, value, label }: { id: string; value: string; label: string }) => <button className="copy-button" onClick={() => void copy(id, value)}>{copied === id ? <Check size={13} /> : <Copy size={13} />}{copied === id ? 'Copied' : label}</button>

  return <div className="hub-layout">
    <section className="hub-intro panel"><div className="hub-icon"><BookOpen size={18} /></div><div><span className="chart-kicker">LIVE GITHUB DATA</span><h2>Sync your repository into a local database.</h2><p>The current app fetches actual pull requests and GitHub Actions runs, stores them in SQLite, and refreshes the cockpit from the API.</p></div></section>
    <div className="architecture panel"><div className="architecture-step"><div className="architecture-icon github-icon">⌘</div><div><strong>GitHub API / Webhooks</strong><span>PRs · reviews · Actions</span></div></div><ArrowRight size={15} className="architecture-arrow" /><div className="architecture-step"><div className="architecture-icon endpoint-icon">↗</div><div><strong>Verify & normalize</strong><span>POST /api/webhooks/github</span></div></div><ArrowRight size={15} className="architecture-arrow" /><div className="architecture-step"><div className="architecture-icon db-icon">◆</div><div><strong>SQLite</strong><span>dashboard/data/</span></div></div></div>
    <div className="hub-doc-grid"><div className="hub-main">
      <section className="panel code-panel"><div className="code-panel-head"><div><span className="chart-kicker">01 / RUN IT LOCALLY</span><h3>Start syncing real GitHub data</h3></div><CopyButton id="setup" value={setup} label="Copy setup" /></div><div className="endpoint-line"><span className="method-post">SYNC</span><code>POST /api/sync</code></div><p className="doc-copy">Run this from <code>dashboard/</code>. Public repos work without a token. Private repos need a GitHub token available only to the backend process.</p><div className="code-block"><div className="code-toolbar"><span><i /> bash</span><button onClick={() => void copy('setup', setup)} aria-label="Copy setup"><Copy size={13} /></button></div><pre>{setup}</pre></div><p className="doc-copy">Then open The Pulse and click <code>Sync GitHub</code>. The default repo is this workspace’s GitHub origin. Set <code>GITHUB_REPOSITORY</code> in <code>.env</code> to use another repo.</p></section>
      <section className="panel code-panel"><div className="code-panel-head"><div><span className="chart-kicker">02 / LABEL ATTRIBUTION</span><h3>Label PRs to compare AI vs human</h3></div><CopyButton id="labels" value={labels} label="Copy labels" /></div><p className="doc-copy">GitHub does not know which model helped write a PR. Add one attribution label and one complexity label. Unlabeled PRs stay “Unknown” and do not enter the comparison.</p><div className="code-block"><div className="code-toolbar"><span><i /> create these GitHub labels</span></div><pre>{labels}</pre></div></section>
      <section className="panel code-panel"><div className="code-panel-head"><div><span className="chart-kicker">03 / DATABASE</span><h3>Local SQLite schema</h3></div><CopyButton id="schema" value={schema} label="Copy SQL" /></div><p className="doc-copy">The server creates these tables in <code>dashboard/data/assist-ledger.sqlite</code> on first start. Back up that file to preserve the imported history.</p><div className="code-block"><div className="code-toolbar"><span><i /> sql · created by server at startup</span><button onClick={() => void copy('schema', schema)} aria-label="Copy schema"><Copy size={13} /></button></div><pre>{schema}</pre></div></section>
    </div><div className="hub-side">
      <section className="panel payload-card"><div className="payload-head"><div><span className="chart-kicker">WEBHOOK EVENT</span><h3>pull_request</h3></div><CopyButton id="pr" value={prPayload} label="Copy" /></div><p>Opened, synchronized, reopened, closed</p><div className="code-block payload-code"><pre>{prPayload}</pre></div><div className="event-header"><span>X-GitHub-Event</span><code>pull_request</code></div></section>
      <section className="panel payload-card"><div className="payload-head"><div><span className="chart-kicker">WEBHOOK EVENT</span><h3>workflow_run</h3></div><CopyButton id="ci" value={ciPayload} label="Copy" /></div><p>Completed Actions runs update the related PR’s CI state</p><div className="code-block payload-code"><pre>{ciPayload}</pre></div><div className="event-header"><span>X-GitHub-Event</span><code>workflow_run</code></div></section>
      <section className="panel code-panel"><div className="code-panel-head"><div><span className="chart-kicker">04 / SIGNATURE CHECK</span><h3>HMAC SHA-256</h3></div><ShieldCheck size={17} className="security-icon" /></div><p className="doc-copy">Set <code>GITHUB_WEBHOOK_SECRET</code> on the server and in GitHub’s webhook settings. The server rejects invalid signatures. To receive webhooks, deploy this server at a public HTTPS URL; GitHub cannot reach localhost.</p><div className="code-block small-code"><pre>{hmac}</pre></div><p className="doc-copy">Subscribe to <code>pull_request</code>, <code>pull_request_review</code>, and <code>workflow_run</code>.</p></section>
      <section className="panel code-panel"><div className="code-panel-head"><div><span className="chart-kicker">05 / LOCAL MODEL TELEMETRY</span><h3>Stream Ollama and RAG usage</h3></div><CopyButton id="model-usage" value={modelUsageCurl} label="Copy curl" /></div><p className="doc-copy">Set the same <code>ASSIST_LEDGER_INGEST_KEY</code> in <code>dashboard/.env</code> and the repo root <code>.env</code>. Point the Python assistant at <code>ASSIST_LEDGER_DASHBOARD_URL=http://127.0.0.1:3000</code> to populate the cockpit table without Supabase.</p><div className="code-block"><div className="code-toolbar"><span><i /> POST /api/telemetry/model-usage</span></div><pre>{modelUsageCurl}</pre></div></section>
      <section className="panel code-panel"><div className="code-panel-head"><div><span className="chart-kicker">06 / PR TOKEN INGESTION</span><h3>Record model usage per PR</h3></div><CopyButton id="token-endpoint" value={tokenCurl} label="Copy curl" /></div><p className="doc-copy">Optional PR-scoped records for the pull request inspector. GitHub does not provide token usage, and ordinary chat usage is not automatically attributed to code changes.</p><div className="code-block"><div className="code-toolbar"><span><i /> POST /api/telemetry/tokens</span></div><pre>{tokenExample}</pre></div></section>
    </div></div>
  </div>
}
