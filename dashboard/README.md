# Assist Ledger

Assist Ledger is a single-user local dashboard connected to this workspace's
GitHub repository. It reads real PR and GitHub Actions data, persists it in
SQLite, and accepts signed GitHub webhook events. It does not generate sample
PRs or fill missing model telemetry with invented values.

## Run the connected application

Requirements: Node.js 22.13 or newer.

```bash
cd dashboard
cp .env.example .env
npm run dev:full
```

Open the Vite URL printed in the terminal (default dev port **5175**; `/api`
proxies to the Node server on **3000**). The default repository is
`Nob1taaaa/LocalAIAgentWithRAG-Assistant`, taken from this project's GitHub
origin. Change `GITHUB_REPOSITORY` in `.env` to another `owner/name`. Public
repositories need no token; for private repos, set a read-only `GITHUB_TOKEN`
in `.env`.

Click **Sync GitHub** in The Pulse to import PR history and GitHub Actions runs.
The SQLite file is `dashboard/data/assist-ledger.sqlite`; it is ignored by Git.
The frontend refreshes from the local API every 15 seconds. The Sync button
fetches GitHub; the timer only reloads local records.

## Live webhooks

For automatic updates, deploy the Node server on a public HTTPS host and set
`HOST=0.0.0.0`, `PORT` to the host's port, and `GITHUB_WEBHOOK_SECRET`. Add a
GitHub webhook pointing to `https://your-host/api/webhooks/github` with the same
secret. Subscribe to `pull_request`, `pull_request_review`, and `workflow_run`.
The server validates `X-Hub-Signature-256`. `localhost` cannot receive events
from GitHub. Keep the dashboard and server behind authentication before exposing
it publicly; the current app is intended for one trusted user.

## Real AI attribution

GitHub does not identify which coding assistant helped with a PR. Add one of
these labels to each PR:

- `assist-ledger:human-only` (study protocol)
- `assist-ledger:ai-assisted` (study protocol)
- `assist-ledger:human`
- `assist-ledger:copilot`
- `assist-ledger:claude`
- `assist-ledger:gpt-4o`

Add one complexity label (`L1` to `L4`) if you want complexity charts. PRs
without labels remain “Unknown” and are excluded from AI vs. human comparisons.

GitHub also does not provide prompt/completion tokens or model costs. To record
those, set `ASSIST_LEDGER_INGEST_KEY` and post to
`POST /api/telemetry/tokens` with the `X-Assist-Ledger-Key` header and a
`pullRequestNumber`, model, token counts, cost, and latency. Instrument the
coding tool or model API proxy that actually sees those values; do not count
unrelated chat usage as code telemetry.

## Build

```bash
npm run build
```

The server's API routes are under `/api`. `server/index.mjs` owns GitHub sync,
webhook validation, token ingestion, and SQLite persistence. The TypeScript
repository in `src/lib/data/repository.ts` talks to that API. Replace the
storage layer with Supabase later if shared hosted data is needed.
