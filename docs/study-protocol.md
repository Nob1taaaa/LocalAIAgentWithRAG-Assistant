# Assist Ledger study protocol

## Research question

How does recorded AI assistance relate to software delivery speed and quality?

## Comparison groups

Every study pull request must have exactly one declared label:

- `assist-ledger:ai-assisted` — a coding assistant contributed to implementation.
- `assist-ledger:human-only` — no generative coding assistant was used for implementation.

Unlabelled PRs are excluded. The label is a participant declaration, not automatic
proof of line authorship. Cursor Agent/Tab hooks provide observed edit events;
tool events can be missing when hooks are disabled or another editor is used.

## Collection

- GitHub provides PR author, dates, merge state, and changed-line counts.
- GitHub Actions provides completed workflow outcome and duration.
- Local instrumentation records model name, token counts, latency, and Cursor
  Agent/Tab edit event counts when available.
- Prompts, completions, document contents, and source diffs are not sent to the
  usage collector.

## Analysis

Report sample counts beside every comparison. Compare median time to merge and
first CI pass rate only for PRs with the corresponding observed data. Show model
token totals only for PR-linked telemetry. Record exclusions and missing data.
Do not infer causation from a small observational sample; task difficulty,
reviewer, and contributor experience can confound the results.

## Suggested pilot

Use 8–10 similarly sized, independent maintenance tasks, split between the two
declared groups. Keep the same repository, review rules, and CI checks. Have the
same reviewer process both groups where possible. Do not fabricate benchmark
rows or count unrelated study/chat activity as code telemetry.
