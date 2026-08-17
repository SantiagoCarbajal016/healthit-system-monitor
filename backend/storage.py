from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_STATE = {
    "remote_machines": {},
    "registered_machines": {},
    "machine_overrides": {},
    "terminal_sessions": {},
    "task_results": {},
}


def database_path() -> Path:
    """Return the SQLite file used for lightweight local persistence."""
    configured = os.getenv("HEALTHIT_DB_PATH", "data/healthit.db")
    return Path(configured)


def connect() -> sqlite3.Connection:
    """Open the local SQLite database and create its folder if needed."""
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def init_db() -> None:
    """Create the tiny state table used by the prototype."""
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                name TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def load_state() -> dict[str, dict[str, Any]]:
    """Load saved dashboard state, falling back cleanly if nothing exists yet."""
    init_db()
    state = {key: dict(value) for key, value in DEFAULT_STATE.items()}
    with connect() as db:
        rows = db.execute("SELECT name, payload FROM app_state").fetchall()
    for name, payload in rows:
        if name not in state:
            continue
        try:
            loaded = json.loads(payload)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            state[name] = loaded
    return state


def save_state(**parts: dict[str, Any]) -> None:
    """Persist whichever state dictionaries changed."""
    init_db()
    with connect() as db:
        for name, payload in parts.items():
            db.execute(
                """
                INSERT INTO app_state (name, payload, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (name, json.dumps(payload, default=str)),
            )
