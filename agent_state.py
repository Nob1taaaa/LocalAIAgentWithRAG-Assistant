"""Persistent user-approved memories, plans, and local agent activity logs."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
STATE_DB = Path(os.environ.get("AGENT_STATE_DB", APP_DIR / "agent_state.sqlite3")).expanduser()
LOG_FILE = Path(os.environ.get("AGENT_LOG_FILE", APP_DIR / "agent.log.jsonl")).expanduser()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_state() -> None:
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATE_DB) as db:
        db.execute("CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, fact TEXT NOT NULL, created_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS plans (id INTEGER PRIMARY KEY, task TEXT NOT NULL, steps TEXT NOT NULL, created_at TEXT NOT NULL)")


def list_memories() -> list[tuple[int, str]]:
    init_state()
    with sqlite3.connect(STATE_DB) as db:
        return db.execute("SELECT id, fact FROM memories ORDER BY id DESC LIMIT 50").fetchall()


def memory_context() -> str:
    saved = list_memories()
    return "\n".join(f"- {fact}" for _, fact in reversed(saved)) or "No saved preferences or project facts."


def save_memory(fact: str) -> int:
    fact = " ".join(fact.split())
    if not fact or len(fact) > 500:
        raise ValueError("Memory must contain 1 to 500 characters.")
    init_state()
    with sqlite3.connect(STATE_DB) as db:
        cursor = db.execute("INSERT INTO memories(fact, created_at) VALUES (?, ?)", (fact, _now()))
        return int(cursor.lastrowid)


def delete_memory(memory_id: int) -> bool:
    init_state()
    with sqlite3.connect(STATE_DB) as db:
        cursor = db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0


def save_plan(task: str, steps: list[str]) -> int:
    init_state()
    items = [{"text": step, "done": False, "evidence": ""} for step in steps]
    with sqlite3.connect(STATE_DB) as db:
        cursor = db.execute("INSERT INTO plans(task, steps, created_at) VALUES (?, ?, ?)",
                             (task, json.dumps(items), _now()))
        return int(cursor.lastrowid)


def current_plan() -> tuple[int, str, list[dict]] | None:
    init_state()
    with sqlite3.connect(STATE_DB) as db:
        row = db.execute("SELECT id, task, steps FROM plans ORDER BY id DESC LIMIT 1").fetchone()
    return (row[0], row[1], json.loads(row[2])) if row else None


def complete_plan_step(step_number: int, evidence: str) -> tuple[bool, str]:
    plan = current_plan()
    if not plan:
        return False, "No current plan."
    plan_id, _task, steps = plan
    index = step_number - 1
    if not 0 <= index < len(steps):
        return False, "That step number is not in the current plan."
    steps[index]["done"] = True
    steps[index]["evidence"] = evidence
    with sqlite3.connect(STATE_DB) as db:
        db.execute("UPDATE plans SET steps = ? WHERE id = ?", (json.dumps(steps), plan_id))
    return True, "Step marked complete."


def log_event(tool: str, arguments: dict, status: str, detail: str = "") -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    event = {"time": _now(), "tool": tool, "arguments": arguments, "status": status, "detail": detail[:500]}
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def recent_logs(limit: int = 10) -> list[str]:
    if not 1 <= limit <= 100:
        raise ValueError("Log limit must be between 1 and 100.")
    if not LOG_FILE.exists():
        return []
    return LOG_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
