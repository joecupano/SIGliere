"""
reference/mac_manifest.py

State tracking for the MAC vendor mirror (mac_mirror.py). Unlike the SigID
mirror (reference/sigid_manifest.py), this is a single-file download, not a
per-page crawl — there's no per-item revision to track, just: what content
hash did we last write, and a log of sync runs (for the timer/validate
scripts to reason about). Deliberately the lightest manifest in reference/;
mirrors sigid_manifest.py's shape (same contextmanager/table style) so
anyone who's read that one recognizes this immediately, without carrying
over machinery this mirror doesn't need (no per-page revision table).

Manifest lives inside the mirror's own output tree
(/data/reference/mac-vendors/manifest.db) — same reasoning as
sigid_manifest.py: it moves with the data if /data ever migrates.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS file_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- single row, single file
    content_hash    TEXT NOT NULL,
    entry_count     INTEGER NOT NULL,
    source_url      TEXT NOT NULL,
    synced_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    outcome         TEXT,           -- 'updated' | 'unchanged' | 'error'
    entry_count     INTEGER,
    status          TEXT,           -- 'success' | 'error'
    error_message   TEXT
);
"""


class MacManifest:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def last_content_hash(self) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT content_hash FROM file_state WHERE id = 1").fetchone()
        return row[0] if row else None

    def record_file_synced(self, content_hash: str, entry_count: int, source_url: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO file_state (id, content_hash, entry_count, source_url, synced_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    entry_count=excluded.entry_count,
                    source_url=excluded.source_url,
                    synced_at=excluded.synced_at
                """,
                (content_hash, entry_count, source_url, datetime.now(timezone.utc).isoformat()),
            )

    def start_run(self) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO sync_runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            return cur.lastrowid

    def finish_run(self, run_id: int, outcome: str, entry_count: int | None, status: str,
                    error_message: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sync_runs
                SET finished_at = ?, outcome = ?, entry_count = ?, status = ?, error_message = ?
                WHERE id = ?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    outcome,
                    entry_count,
                    status,
                    error_message,
                    run_id,
                ),
            )

    def last_successful_run_time(self) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT started_at FROM sync_runs WHERE status = 'success' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else None
