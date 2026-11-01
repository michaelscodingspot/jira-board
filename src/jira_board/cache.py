"""Local SQLite cache so the board shows at once on startup and previews appear without waiting on Jira.

Lives at $XDG_CACHE_HOME/jira-board/cache.db (default ~/.cache/jira-board/cache.db).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from .jira import Column, Issue

SCHEMA = """
CREATE TABLE IF NOT EXISTS board (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    columns    TEXT NOT NULL,  -- JSON: [[name, [status ids]], ...]
    fetched_at REAL NOT NULL
);

-- Last fetched issue list per board, in board rank order (position).
CREATE TABLE IF NOT EXISTS issues (
    key         TEXT PRIMARY KEY,
    board_id    INTEGER NOT NULL,
    summary     TEXT NOT NULL,
    type        TEXT NOT NULL,
    status_id   TEXT NOT NULL,
    status_name TEXT NOT NULL,
    labels      TEXT NOT NULL,  -- JSON array
    comments    INTEGER NOT NULL,
    created     TEXT NOT NULL,
    updated     TEXT NOT NULL,
    position    INTEGER NOT NULL
);

-- Full issue JSON for the preview, reused while the issue's `updated` is unchanged.
CREATE TABLE IF NOT EXISTS issue_detail (
    key        TEXT PRIMARY KEY,
    updated    TEXT NOT NULL,
    data       TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
"""


def default_path() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "jira-board" / "cache.db"


class Cache:
    def __init__(self, path: Path | None = None) -> None:
        path = path or default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    # ---------- board ----------

    def board(self, board_id: int) -> tuple[str, list[Column]] | None:
        row = self.db.execute("SELECT name, columns FROM board WHERE id = ?", (board_id,)).fetchone()
        if not row:
            return None
        return row[0], [Column(name, tuple(ids)) for name, ids in json.loads(row[1])]

    def put_board(self, board_id: int, name: str, columns: list[Column]) -> None:
        data = json.dumps([[c.name, list(c.status_ids)] for c in columns])
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO board (id, name, columns, fetched_at) VALUES (?, ?, ?, ?)",
                (board_id, name, data, time.time()),
            )

    # ---------- issues ----------

    def issues(self, board_id: int) -> list[Issue]:
        rows = self.db.execute(
            "SELECT key, summary, type, status_id, status_name, labels, comments, created, updated"
            " FROM issues WHERE board_id = ? ORDER BY position",
            (board_id,),
        )
        return [Issue(r[0], r[1], r[2], r[3], r[4], tuple(json.loads(r[5])), r[6], r[7], r[8]) for r in rows]

    def save_issues(self, board_id: int, issues: list[Issue]) -> None:
        """Replace the board's issue list; list order becomes `position`."""
        with self.db:
            self.db.execute("DELETE FROM issues WHERE board_id = ?", (board_id,))
            self.db.executemany(
                "INSERT OR REPLACE INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (i.key, board_id, i.summary, i.type, i.status_id, i.status_name,
                     json.dumps(list(i.labels)), i.comments, i.created, i.updated, pos)
                    for pos, i in enumerate(issues)
                ],
            )

    # ---------- preview ----------

    def detail(self, key: str) -> tuple[str, dict] | None:
        row = self.db.execute("SELECT updated, data FROM issue_detail WHERE key = ?", (key,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def put_detail(self, key: str, data: dict) -> None:
        updated = (data.get("fields") or {}).get("updated") or ""
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO issue_detail (key, updated, data, fetched_at) VALUES (?, ?, ?, ?)",
                (key, updated, json.dumps(data), time.time()),
            )

    def forget_detail(self, key: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM issue_detail WHERE key = ?", (key,))
