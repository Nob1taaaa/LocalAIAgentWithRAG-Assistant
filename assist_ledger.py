"""Send model usage counts to Assist Ledger without sending prompts or documents."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def _usage_payload(answer, model_name: str, client: str) -> dict:
    metadata = getattr(answer, "response_metadata", {}) or {}
    usage = getattr(answer, "usage_metadata", {}) or {}
    prompt_tokens = metadata.get("prompt_eval_count", usage.get("input_tokens", 0))
    completion_tokens = metadata.get("eval_count", usage.get("output_tokens", 0))
    duration_ns = metadata.get("total_duration")
    latency_ms = round(duration_ns / 1_000_000) if isinstance(duration_ns, (int, float)) else None
    raw_pr_number = os.environ.get("ASSIST_LEDGER_PULL_REQUEST_NUMBER", "")
    return {
        "repository": os.environ.get("ASSIST_LEDGER_REPOSITORY", "Nob1taaaa/LocalAIAgentWithRAG-Assistant"),
        "pull_request_number": int(raw_pr_number) if raw_pr_number.isdigit() else None,
        "provider": "ollama",
        "client": client,
        "model": model_name,
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "latency_ms": latency_ms,
    }


def _post_json(url: str, payload: dict, headers: dict) -> bool:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        print(f"Assist Ledger telemetry was not accepted (HTTP {exc.code}); local answering is unaffected.")
        return False
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def report_usage(answer, model_name: str, client: str = "python-rag") -> bool:
    """Best-effort metadata upload; returns True if any configured destination accepted the event."""
    ingest_key = os.environ.get("ASSIST_LEDGER_INGEST_KEY", "").strip()
    payload = _usage_payload(answer, model_name, client)
    headers = {
        "Content-Type": "application/json",
        "x-assist-ledger-key": ingest_key,
    }
    if os.environ.get("SUPABASE_PUBLISHABLE_KEY"):
        headers["apikey"] = os.environ["SUPABASE_PUBLISHABLE_KEY"]

    accepted = False
    dashboard_url = os.environ.get("ASSIST_LEDGER_DASHBOARD_URL", "").strip().rstrip("/")
    if dashboard_url and ingest_key:
        accepted = _post_json(f"{dashboard_url}/api/telemetry/model-usage", payload, headers) or accepted

    function_url = os.environ.get("ASSIST_LEDGER_FUNCTION_URL", "").strip()
    if function_url and ingest_key:
        accepted = _post_json(function_url, payload, headers) or accepted

    if not accepted and function_url and ingest_key:
        print("Assist Ledger telemetry could not reach Supabase; local answering is unaffected.")
    return accepted
