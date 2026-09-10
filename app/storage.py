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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entity_index (
                value          TEXT NOT NULL,
                type           TEXT NOT NULL,
                observation_id INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_value ON entity_index(value)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_obs ON entity_index(observation_id)")
        # Risultati dei lookup live. Tabella dedicata, NON un allargamento di
        # `enrichment_json`: quel blob viene riscritto per intero a ogni
        # salvataggio e riletto con json.loads a ogni get_by_id, quindi farlo
        # crescere farebbe pagare il costo del raw anche alle rotte che non lo
        # usano. Qui invece si aggiorna una riga per volta e si legge a richiesta.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lookup_results (
                observation_id INTEGER NOT NULL,
                resource_id    TEXT    NOT NULL,
                entity_value   TEXT    NOT NULL,
                fetched_at     TEXT    NOT NULL,
                ok             INTEGER NOT NULL,
                result_json    TEXT    NOT NULL,
                PRIMARY KEY (observation_id, resource_id, entity_value)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lookup_obs ON lookup_results(observation_id)")


def reset_db() -> None:
    """Svuota tutte le osservazioni: DROP della tabella + ricrea lo schema vuoto.
    Idempotente. Usato per ripartire da DB pulito (admin/test)."""
    with _connect() as conn:
        conn.execute("DROP TABLE IF EXISTS observations")
        conn.execute("DROP TABLE IF EXISTS entity_index")
        conn.execute("DROP TABLE IF EXISTS lookup_results")
    init_db()


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
        seen: set[tuple] = set()
        for e in payload:
            key = (e["type"], e["value"])
            if key in seen:
                continue
            seen.add(key)
            conn.execute(
                "INSERT INTO entity_index (value, type, observation_id) VALUES (?, ?, ?)",
                (e["value"], e["type"], rowid),
            )
        return rowid


def rebuild_index() -> None:
    """Svuota e ricostruisce entity_index da observations (DB pre-feature / manutenzione)."""
    with _connect() as conn:
        conn.execute("DELETE FROM entity_index")
        rows = conn.execute("SELECT id, entities_json FROM observations").fetchall()
        for r in rows:
            try:
                entities = json.loads(r["entities_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            seen: set[tuple] = set()
            for e in entities:
                key = (e.get("type"), e.get("value"))
                if key[0] is None or key[1] is None or key in seen:
                    continue
                seen.add(key)
                conn.execute(
                    "INSERT INTO entity_index (value, type, observation_id) VALUES (?, ?, ?)",
                    (e["value"], e["type"], r["id"]),
                )


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
        conn.execute(
            "DELETE FROM entity_index WHERE observation_id=? AND type=? AND value=?",
            (observation_id, entity_type, entity_value),
        )


def _dedup_key(etype: str, value: str) -> tuple[str, str]:
    """Chiave di confronto per il dedup di add_entities: normalizza spazi
    multipli e punteggiatura finale, così LLM extractor e regex_extractor non
    duplicano lo stesso valore (es. address) per differenze di formattazione
    marginali. Il VALORE salvato resta quello originale, invariato."""
    normalized = " ".join(value.split()).rstrip(".,;:")
    return (etype, normalized)


def add_entities(observation_id: int, new_entities: list[Entity]) -> None:
    """Aggiunge entità a un'osservazione, deduplicando per (type, value)
    normalizzato (vedi _dedup_key)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT entities_json FROM observations WHERE id = ?", (observation_id,)
        ).fetchone()
        if not row:
            return
        existing = json.loads(row["entities_json"])
        seen = {_dedup_key(e.get("type"), e.get("value")) for e in existing}
        for e in new_entities:
            d = e.to_dict()
            key = _dedup_key(d["type"], d["value"])
            if key not in seen:
                existing.append(d)
                seen.add(key)
                conn.execute(
                    "INSERT INTO entity_index (value, type, observation_id) VALUES (?, ?, ?)",
                    (d["value"], d["type"], observation_id),
                )
        conn.execute(
            "UPDATE observations SET entities_json = ? WHERE id = ?",
            (json.dumps(existing, ensure_ascii=False), observation_id),
        )


def delete_observation(observation_id: int) -> None:
    """Elimina permanentemente un'osservazione dal DB."""
    with _connect() as conn:
        conn.execute("DELETE FROM observations WHERE id = ?", (observation_id,))
        conn.execute("DELETE FROM entity_index WHERE observation_id=?", (observation_id,))
        # I risultati dei lookup contengono PII (account trovati, dati anagrafici
        # decodificati, operatore telefonico): devono sparire con l'osservazione,
        # non restare in un DB da cui l'utente credeva di averli tolti.
        conn.execute("DELETE FROM lookup_results WHERE observation_id=?", (observation_id,))


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
            # B608 soppresso a ragion veduta: `where` non viene dall'utente ma da
            # un dict con default '' — nessun input arbitrario raggiunge la query,
            # e `limit` passa come parametro. Il nosec va sulla riga che bandit
            # riporta (quella dell'interpolazione), altrimenti avverte del
            # disallineamento a ogni scan.
            f"SELECT id, timestamp, raw_input, entities_json, kept, label "
            f"FROM observations {where} ORDER BY id DESC LIMIT ?",  # nosec B608
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


def observations_with_value(value: str) -> list[dict]:
    """Osservazioni che contengono l'entità `value` (via entity_index)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT o.id, o.timestamp, o.label, o.kept "
            "FROM entity_index ei JOIN observations o ON ei.observation_id = o.id "
            "WHERE ei.value = ? ORDER BY o.id DESC",
            (value,),
        ).fetchall()
    return [
        {"id": r["id"], "timestamp": r["timestamp"],
         "label": r["label"] if r["label"] else None, "kept": bool(r["kept"])}
        for r in rows
    ]


def related_entities(value: str, limit: int = 30) -> list[dict]:
    """Entità che co-occorrono con `value` nelle stesse osservazioni (escluso sé stesso)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ei2.type AS type, ei2.value AS value, "
            "COUNT(DISTINCT ei2.observation_id) AS shared "
            "FROM entity_index ei1 "
            "JOIN entity_index ei2 ON ei1.observation_id = ei2.observation_id "
            "WHERE ei1.value = ? AND ei2.value != ? "
            "GROUP BY ei2.type, ei2.value "
            "ORDER BY shared DESC, ei2.value ASC LIMIT ?",
            (value, value, limit),
        ).fetchall()
    return [{"type": r["type"], "value": r["value"], "shared": r["shared"]} for r in rows]


def counts_for_values(values: list[str]) -> dict[str, int]:
    """Per ogni valore, in quante osservazioni distinte appare. Batch (una query)."""
    if not values:
        return {}
    placeholders = ",".join("?" for _ in values)
    with _connect() as conn:
        rows = conn.execute(
            # B608 soppresso: `placeholders` e' solo una sequenza di "?" — i
            # valori passano come parametri. Vedi la nota in get_recent().
            f"SELECT value, COUNT(DISTINCT observation_id) AS n "
            f"FROM entity_index WHERE value IN ({placeholders}) GROUP BY value",  # nosec B608
            tuple(values),
        ).fetchall()
    return {r["value"]: r["n"] for r in rows}


def ensure_index() -> None:
    """Auto-heal: se entity_index è vuoto ma ci sono osservazioni (DB pre-feature),
    ricostruiscilo. No-op negli altri casi."""
    with _connect() as conn:
        idx = conn.execute("SELECT COUNT(*) AS n FROM entity_index").fetchone()["n"]
        obs = conn.execute("SELECT COUNT(*) AS n FROM observations").fetchone()["n"]
    if idx == 0 and obs > 0:
        rebuild_index()


# ── Risultati dei lookup live ───────────────────────────────────────────────
#
# Prima stavano in un dict globale in RAM. Tre conseguenze, tutte invisibili
# finche' non le si cerca: la sintesi investigativa vedeva zero dati live se
# l'utente non aveva prima espanso a mano le card; gli export dopo un riavvio
# erano poveri; ogni riapertura di una card ri-colpiva le API bruciando quota.
# Persistendoli, l'analisi AI riceve tutto quel che POE ha raccolto, anche da
# sessioni precedenti.

def save_lookup_result(observation_id: int, resource_id: str, entity_value: str,
                       result: dict) -> None:
    """Salva (o aggiorna) l'esito di un lookup. Non solleva mai.

    Salvare e' un effetto collaterale del lookup: se fallisce — un risultato non
    serializzabile, il disco pieno — l'utente deve comunque vedere a schermo il
    dato che ha appena chiesto."""
    try:
        blob = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        logger.warning("lookup non serializzabile, non salvato: %s/%s",
                       resource_id, entity_value)
        return
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lookup_results "
                "(observation_id, resource_id, entity_value, fetched_at, ok, result_json) "
                "VALUES (?,?,?,?,?,?)",
                (observation_id, resource_id, entity_value,
                 datetime.now(timezone.utc).isoformat(),
                 1 if result.get("ok") else 0, blob),
            )
    except sqlite3.Error:
        logger.warning("lookup non salvato (%s/%s)", resource_id, entity_value,
                       exc_info=True)


def get_lookup_results(observation_id: int,
                       entity_value: str | None = None) -> dict[str, dict]:
    """`{valore_entita: {resource_id: risultato}}` per un'osservazione.

    Una riga illeggibile viene saltata: un JSON corrotto a riposo non deve
    impedire di leggere tutte le altre fonti."""
    sql = ("SELECT entity_value, resource_id, result_json FROM lookup_results "
           "WHERE observation_id = ?")
    params: tuple = (observation_id,)
    if entity_value is not None:
        sql += " AND entity_value = ?"
        params += (entity_value,)
    out: dict[str, dict] = {}
    try:
        with _connect() as conn:
            for valore, rid, blob in conn.execute(sql, params):
                try:
                    out.setdefault(valore, {})[rid] = json.loads(blob)
                except (TypeError, ValueError):
                    logger.warning("lookup illeggibile a riposo: %s/%s", rid, valore)
    except sqlite3.OperationalError:
        # DB aperto prima della migrazione (versione precedente, o un percorso
        # su cui init_db non e' ancora passata): "nessun lookup salvato" e' la
        # risposta onesta, e leggere non deve mai far cadere una rotta.
        logger.debug("tabella lookup_results assente", exc_info=True)
    return out


def count_lookup_results() -> int:
    """Quante righe di lookup ci sono in tutto. Per i test e per stimare la
    crescita del DB."""
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM lookup_results").fetchone()[0]
