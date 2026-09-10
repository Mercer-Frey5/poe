"""store.py — persistenza SQLite dei feed reputation (DB separato da poe.db)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

REP_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "reputation.db"


def _connect() -> sqlite3.Connection:
    REP_DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(REP_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_rep_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS reputation ("
            "value TEXT NOT NULL, type TEXT NOT NULL, source TEXT NOT NULL, "
            "threat TEXT, reference TEXT, updated_at TEXT)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rep_value ON reputation(value)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS feed_meta ("
            "source TEXT PRIMARY KEY, updated_at TEXT, rows INTEGER)"
        )


def replace_source(source: str, rows: list[dict]) -> None:
    """Sostituisce tutte le righe di una sorgente (delete + insert) in transazione."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute("DELETE FROM reputation WHERE source = ?", (source,))
        conn.executemany(
            "INSERT INTO reputation (value, type, source, threat, reference, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(r["value"], r["type"], source, r.get("threat"), r.get("reference"), now)
             for r in rows],
        )
        conn.execute(
            "INSERT INTO feed_meta (source, updated_at, rows) VALUES (?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET updated_at=excluded.updated_at, rows=excluded.rows",
            (source, now, len(rows)),
        )


def lookup(value: str) -> list[dict]:
    """Righe reputation per un valore esatto. [] se sconosciuto."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT source, type, threat, reference, updated_at FROM reputation WHERE value = ?",
            (value,),
        ).fetchall()
    return [dict(r) for r in rows]


def is_stale(source: str, ttl_hours: float) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT updated_at FROM feed_meta WHERE source = ?", (source,)
        ).fetchone()
    if not row or not row["updated_at"]:
        return True
    try:
        last = datetime.fromisoformat(row["updated_at"])
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - last) > timedelta(hours=ttl_hours)


def feed_status() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT source, updated_at, rows FROM feed_meta ORDER BY source"
        ).fetchall()
    return [dict(r) for r in rows]
