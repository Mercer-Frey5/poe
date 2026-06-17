"""
storage.py — persistenza SQLite di POE v0.4.

Schema tabella invariato (una sola tabella `observations`).
Il payload JSON entities_json cresce in v0.4: ogni entità ora ha
{type, value, original, confidence, metadata, derived_from}.

Backfill in lettura per entità storiche v0.2/v0.3:
- `original` mancante → valore di `value`
- `confidence` mancante → 'medium' (default conservativo)
- `metadata` mancante → {}
- `derived_from` mancante → None

v0.4 aggiunge colonna `kept` alla tabella observations per C2
(cronologia curabile minimale). La colonna viene aggiunta via ALTER
TABLE se mancante (safe migration additive).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models import Entity

logger = logging.getLogger(__name__)


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "poe.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Crea la tabella se non esiste e applica migrazioni additive. Idempotente."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp      TEXT NOT NULL,
                raw_input      TEXT NOT NULL,
                entities_json  TEXT NOT NULL,
                kept           INTEGER NOT NULL DEFAULT 0,
                label          TEXT
            )
            """
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        # Migrazioni additive idempotenti. Filtra per messaggio "duplicate
        # column": altri OperationalError (DB locked, disk full) devono
        # propagare invece di essere silenziati.
        for migration in (
            "ALTER TABLE observations ADD COLUMN kept INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE observations ADD COLUMN label TEXT",
        ):
            try:
                conn.execute(migration)
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
        for col_sql in [
            "ALTER TABLE observations ADD COLUMN synthesis_text TEXT",
            "ALTER TABLE observations ADD COLUMN synthesis_model TEXT",
            "ALTER TABLE observations ADD COLUMN enrichment_json TEXT",
        ]:
            try:
                conn.execute(col_sql)
            except Exception:
                pass  # column already exists


def save_observation(raw_input: str, entities: list[Entity]) -> int:
    """Salva un'osservazione e ritorna l'id autoincrementale."""
    payload = [e.to_dict() for e in entities]
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO observations (timestamp, raw_input, entities_json, kept) "
            "VALUES (?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                raw_input,
                json.dumps(payload, ensure_ascii=False),
                0,
            ),
        )
        rowid = cursor.lastrowid
        if rowid is None:
            raise RuntimeError("INSERT did not return a lastrowid")
        return rowid


def set_label(observation_id: int, label: str | None) -> None:
    """Imposta il nome personalizzato di un'osservazione (None = nessun label)."""
    value = label.strip() if label and label.strip() else None
    with _connect() as conn:
        conn.execute(
            "UPDATE observations SET label = ? WHERE id = ?",
            (value, observation_id),
        )


def remove_entity(observation_id: int, entity_type: str, entity_value: str) -> None:
    """Rimuove una singola entità dall'osservazione (aggiorna il JSON in-place)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT entities_json FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
        if not row:
            return
        entities = json.loads(row["entities_json"])
        entities = [
            e for e in entities
            if not (e.get("type") == entity_type and e.get("value") == entity_value)
        ]
        conn.execute(
            "UPDATE observations SET entities_json = ? WHERE id = ?",
            (json.dumps(entities, ensure_ascii=False), observation_id),
        )


def delete_observation(observation_id: int) -> None:
    """Elimina permanentemente un'osservazione dal DB."""
    with _connect() as conn:
        conn.execute("DELETE FROM observations WHERE id = ?", (observation_id,))


def set_kept(observation_id: int, kept: bool) -> None:
    """Imposta il flag kept su un'osservazione (C2 — cronologia curabile)."""
    with _connect() as conn:
        conn.execute(
            "UPDATE observations SET kept = ? WHERE id = ?",
            (1 if kept else 0, observation_id),
        )


def get_recent(limit: int = 10, filter_kept: str = 'all') -> list[dict]:  # noqa: E501
    """
    Ritorna le osservazioni recenti.

    filter_kept:
      'all'   — tutte le osservazioni (default, comportamento v0.3)
      'kept'  — solo quelle con kept=1
      'draft' — solo quelle con kept=0
    """
    where = {
        'all':   '',
        'kept':  'WHERE kept = 1',
        'draft': 'WHERE kept = 0',
    }.get(filter_kept, '')

    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, timestamp, raw_input, entities_json, kept, label "  # nosec B608
            f"FROM observations {where} ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_by_id(observation_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, timestamp, raw_input, entities_json, kept, label, "
            "synthesis_text, synthesis_model, enrichment_json "
            "FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def _row_to_dict(row: sqlite3.Row) -> dict:
    try:
        entities = json.loads(row["entities_json"])
    except json.JSONDecodeError:
        logger.warning("Malformed entities_json for row id=%s — returning empty list", row["id"])
        entities = []

    # Load enrichment cache so geo/WHOIS data survives page reload.
    # enrichment_json = {entity_value: metadata_dict} — merged into entity.metadata.
    enrichment_cache: dict = {}
    if "enrichment_json" in row.keys() and row["enrichment_json"]:
        try:
            enrichment_cache = json.loads(row["enrichment_json"])
        except json.JSONDecodeError:
            pass

    # Backfill per entità storiche v0.1/v0.2/v0.3
    for e in entities:
        if "original" not in e:
            e["original"] = e.get("value", "")
        if "confidence" not in e:
            e["confidence"] = "medium"
        if "metadata" not in e:
            e["metadata"] = {}
        if "derived_from" not in e:
            e["derived_from"] = None
        cached = enrichment_cache.get(e["value"])
        if cached:
            e["metadata"] = {**e["metadata"], **cached}

    result = {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "raw_input": row["raw_input"],
        "entities": entities,
        "kept": bool(row["kept"]),
        "label": row["label"] if row["label"] else None,
    }
    result["synthesis_text"] = row["synthesis_text"] if "synthesis_text" in row.keys() else None
    result["synthesis_model"] = row["synthesis_model"] if "synthesis_model" in row.keys() else None
    result["enrichment_json"] = row["enrichment_json"] if "enrichment_json" in row.keys() else None
    return result


def save_synthesis(observation_id: int, text: str, model: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE observations SET synthesis_text = ?, synthesis_model = ? WHERE id = ?",
            (text, model, observation_id),
        )


def get_synthesis(observation_id: int) -> tuple[str, str] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT synthesis_text, synthesis_model FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    if row and row["synthesis_text"]:
        return row["synthesis_text"], row["synthesis_model"] or ""
    return None


def save_enrichment(observation_id: int, enrichment: dict) -> None:
    import json as _json
    with _connect() as conn:
        conn.execute(
            "UPDATE observations SET enrichment_json = ? WHERE id = ?",
            (_json.dumps(enrichment, ensure_ascii=False), observation_id),
        )


def get_enrichment(observation_id: int) -> dict:
    import json as _json
    with _connect() as conn:
        row = conn.execute(
            "SELECT enrichment_json FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    if row and row["enrichment_json"]:
        return _json.loads(row["enrichment_json"])
    return {}


def find_observations_with_entity(entity_value: str) -> list[dict]:
    """Return observations whose entities_json contains the given value (LIKE search).

    Wildcards are escaped to prevent LIKE over-matching on % and _ chars.
    """
    safe = entity_value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, timestamp, raw_input, entities_json, kept, label, "
            "synthesis_text, synthesis_model, enrichment_json "
            "FROM observations WHERE entities_json LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT 50",
            (f"%{safe}%",),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]
