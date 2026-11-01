# LocalAIAgentWithRAG

This repository also includes **Assist Ledger**, a separate React telemetry and
benchmarking dashboard under [`dashboard/`](dashboard/README.md). It can run
alongside the Python learning assistant without changing its setup.

A local, general-purpose learning assistant that answers with an Ollama model and can retrieve relevant passages from documents you choose. It is no longer tied to the restaurant review demo.

## What it can do

- Index TXT, Markdown, CSV, PDF, and DOCX files, including folders of supported files.
- Keep documents in topic workspaces and search one workspace or all workspaces.
- Combine vector similarity with BM25 keyword matches, then fuse their rankings.
- Evaluate retrieval recall, reciprocal rank, answer facts, and citation validity against a small case set.
- Cite retrieved filenames and PDF pages or CSV rows in answers.
- Switch between direct answers, step-by-step explanations, study help, quizzes, and Socratic questions.
- Use recent messages as context during the current session.
- Save, inspect, and delete user-approved memories across sessions.
- Plan multi-step tasks, track progress, and ask the model to review completion evidence.
- Use bounded, allowlisted tools for document search, source listing, and arithmetic.
- Validate citations against retrieved source labels and log tool calls and outcomes.
- Keep the model, embeddings, and vector database local through Ollama and Chroma.

The assistant does not fine-tune itself from questions. Uploaded documents are indexed so relevant passages can be retrieved later. When no uploaded source matches, the configured local model can answer from its built-in knowledge and will identify that it did not use an uploaded source. Web search is not included; cross-session memory is opt-in through `/remember`.

## Requirements

- Python 3.10 or newer
- Ollama running locally
- A chat model and an embedding model available in Ollama

The defaults are `llama3.2:3b` for chat and `mxbai-embed-large` for embeddings. If needed, install them with:

```bash
ollama pull llama3.2:3b
ollama pull mxbai-embed-large
```

Install the Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run the assistant:

```bash
python3 main.py
```

## Improve and evaluate retrieval

Retrieval combines Ollama vector similarity with local BM25 keyword search and
uses reciprocal rank fusion. The lexical corpus is cached per workspace and
rebuilt after indexing or removing a source. For workspaces above 20,000 chunks,
lexical search is skipped to limit memory use; vector search still works. Set
`RAG_MAX_LEXICAL_INDEX_DOCUMENTS` to adjust that threshold.

The evaluation set in `eval_cases.jsonl` is editable and uses the bundled
restaurant-review CSV as a small example corpus. Index it in the `general`
workspace, then run retrieval checks:

```text
python3 main.py
/add "realistic_restaurant_reviews.csv"
/exit
python3 evaluate.py
```

Add `--answers` to also call Ollama and score required answer facts and citations:

```bash
python3 evaluate.py --answers
```

Use your own documents and questions by editing `eval_cases.jsonl`. Expected
source names and `retrieval_terms` check which evidence reaches the context;
`answer_terms` check key facts in generated answers. The report includes source
recall, source and evidence MRR, retrieval fact coverage, citation validity, and
answer fact coverage. These checks are useful
regression signals, but they do not replace a human review for quality or safety.

## Commands

```text
/help                    Show all commands
/add "./my study files"  Index a file or folder in the current workspace
/sources                 List indexed files in the current workspace
/remove notes.pdf        Remove an indexed source from the current workspace
/memory                  List saved memories
/remember <fact>         Save a preference or project fact
/forget <id>             Delete a saved memory
/plan <task>             Create a persistent 3 to 6 step plan
/plan-status             Show the current plan and evidence
/done <n> <evidence>     Ask the model to check evidence, then confirm completion
/logs [n]                Show the last n tool events (default 10)
/agent <task>            Use model-directed tools for a multi-step task
/workspace biology       Switch to the biology workspace
/workspace all           Search across all workspaces
/mode explain            Explain step by step
/mode study              Teach and give a practice question
/mode quiz               Quiz one question at a time
/mode socratic           Guide with questions
/mode answer             Return to direct answers
/clear                   Clear recent conversation context
/exit                    Quit
```

Supported file extensions: `.txt`, `.md`, `.csv`, `.pdf`, `.docx`. Quote paths that contain spaces. PDF indexing uses `pypdf`, included in the requirements.

## Configuration

You can override the defaults with environment variables:

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
OLLAMA_CHAT_MODEL=llama3.2:3b \
OLLAMA_EMBEDDING_MODEL=mxbai-embed-large \
RAG_DB_DIR=./knowledge_base_db \
python3 main.py
```

By default, chat and embeddings connect directly to Ollama at `http://127.0.0.1:11434`, so the optional telemetry proxy is not needed to run the assistant. To send requests through the proxy instead, set `OLLAMA_BASE_URL=http://127.0.0.1:11435` and start it with `python3 ollama_telemetry_proxy.py` in a separate terminal. Ollama itself must be running in either setup; open the Ollama app or run `ollama serve`.

The fast chat path streams tokens, retrieves documents directly before one model
call, and keeps Ollama models loaded (`OLLAMA_KEEP_ALIVE=10m`, embeddings
`OLLAMA_EMBEDDING_KEEP_ALIVE=600`). Answers are capped at 256 tokens by default
with a 4096-token context. Lower `OLLAMA_NUM_PREDICT` for shorter/faster answers;
increase it when you need longer explanations. Ordinary questions use the fast
path. Prefix a complex request with `/agent` to use model-directed tools, which
may take longer because the model can make several calls.

The vector database is stored in `knowledge_base_db` by default. Recent conversation context stays in memory for the current run and is cleared when the app exits. User-approved memories and plans persist in `agent_state.sqlite3`; tool calls and outcomes are appended to `agent.log.jsonl`. Override those paths with `AGENT_STATE_DB` and `AGENT_LOG_FILE`.

## Agent tools and safety

The model can call only three bounded tools: search the active knowledge workspace, list its indexed sources, and calculate basic arithmetic. Tool arguments are validated, calls are capped at four per turn, and each call is logged. Retrieved documents are treated as untrusted reference text. The model cannot edit source files, send messages, or make purchases. Indexing a path requires your explicit `/add` command, and removing indexed content asks for confirmation.

Memories are stored only when you explicitly use `/remember`; inspect and delete them with `/memory` and `/forget`. A plan is a proposal. `/done` asks the model to review evidence, then requires your confirmation before marking the step complete. Citation labels are checked against sources returned by search; a warning appears for unknown or missing citations when search results were used.

## Optional: report local Ollama usage to Assist Ledger

The assistant can report model name, prompt/completion token counts, latency,
repository, and an optional manually selected PR number to the Assist Ledger
Supabase function. It never sends prompts, retrieved passages, filenames, or
answers. Ollama's local API charge is recorded as `$0`; electricity cost is not
estimated. Telemetry is best-effort, so a Supabase/network error does not stop
the local assistant.

After deploying `record-model-usage` from the Assist Ledger project, copy
`.env.example` to `.env`, then set the function URL and its dedicated ingestion
key. Keep `.env` private; never commit it or use the Supabase service-role key
in this app. The publishable key can be copied from the Assist Ledger
`.env.local`; it is a client key and is protected by the function's separate
ingestion key.

## Open and work on this project in Cursor

Cursor is open to this repository. The Continue extension is configured in
`~/.continue/config.yaml` to use your local `llama3.2:3b` chat model and
`mxbai-embed-large` embeddings. In Cursor, open the Continue panel, choose the
local Llama model, and ask a code question with `@Codebase` context, such as
"Explain the retrieval flow and cite the files you used." The project starts a
loopback-only Ollama proxy when Cursor opens this workspace so Continue chat
calls can report token counts and latency. The proxy forwards model requests to
local Ollama; it sends only usage metadata to Assist Ledger. Cursor hooks count
Agent and Tab edits and send event metadata and edit-size counts, never file
paths or source text.

The proxy listens on `127.0.0.1:11435` and forwards to Ollama on
`127.0.0.1:11434`. Keep Ollama running while using Continue. You can also start
the proxy manually from the integrated terminal with `python3 ollama_telemetry_proxy.py`.

These hooks do not label hand-edited lines as human-written. GitHub records
which account authored a commit or PR, but mixed human/AI diffs need explicit
review or labeling to attribute individual changes accurately.

## CI and study labels

The `.github/workflows/ci.yml` workflow checks Python syntax and builds the
repository dashboard on pull requests and pushes to `main`. The
`telemetry.yml` workflow reports completed PR workflow results to Assist Ledger.
To enable that report, add the local `ASSIST_LEDGER_INGEST_KEY` value as a
GitHub Actions secret named `ASSIST_LEDGER_INGEST_KEY`, and add the Supabase
publishable key as the Actions variable `SUPABASE_PUBLISHABLE_KEY`. Never use
the Supabase service-role key in GitHub Actions.

Label study pull requests with exactly one of `assist-ledger:ai-assisted` or
`assist-ledger:human-only`. The importer uses those labels for the live
comparison; unlabelled PRs remain outside the study. See
[`docs/study-protocol.md`](docs/study-protocol.md) for collection and analysis
limits. Continue's model calls are currently local and are not yet included in
the token-usage table; the Python RAG CLI is instrumented.
