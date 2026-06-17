"""
test_storage.py — test sullo storage SQLite v0.2.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import storage
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(storage, "DB_PATH", db_file)
    storage.init_db()
    return db_file


def test_init_db_idempotent(temp_db):
    storage.init_db()
    storage.init_db()


def test_save_and_retrieve(temp_db):
    entities = [
        Entity("email", "a@b.com"),
        Entity("ipv4", "1.2.3.4"),
    ]
    obs_id = storage.save_observation("testo di input", entities)
    assert isinstance(obs_id, int)

    retrieved = storage.get_by_id(obs_id)
    assert retrieved is not None
    assert retrieved["raw_input"] == "testo di input"
    assert len(retrieved["entities"]) == 2
    # In v0.2 ogni entità deve avere il campo `original`
    for e in retrieved["entities"]:
        assert "original" in e


def test_save_with_deobfuscated_entity(temp_db):
    """Original e value diversi devono essere preservati nello storage."""
    e = Entity(type="url", value="https://evil.com", original="hxxps://evil[.]com")
    obs_id = storage.save_observation("input", [e])
    retrieved = storage.get_by_id(obs_id)
    assert retrieved["entities"][0]["value"] == "https://evil.com"
    assert retrieved["entities"][0]["original"] == "hxxps://evil[.]com"


def test_legacy_entity_without_original_backfilled(temp_db):
    """
    Se un record JSON (es. residuo di v0.1) non contiene `original`,
    storage deve fare backfill con value per coerenza.
    """
    import json
    # Simulo direttamente un INSERT con payload v0.1-style
    with storage._connect() as conn:
        conn.execute(
            "INSERT INTO observations (timestamp, raw_input, entities_json) "
            "VALUES (?, ?, ?)",
            ("2024-01-01T00:00:00", "legacy", json.dumps([{"type": "email", "value": "a@b.com"}])),
        )
    rows = storage.get_recent(limit=1)
    assert rows[0]["entities"][0]["original"] == "a@b.com"


def test_get_recent_ordering(temp_db):
    id1 = storage.save_observation("prima", [])
    id2 = storage.save_observation("seconda", [])
    id3 = storage.save_observation("terza", [])

    recent = storage.get_recent(limit=10)
    assert [r["id"] for r in recent] == [id3, id2, id1]


def test_get_recent_limit(temp_db):
    for i in range(5):
        storage.save_observation(f"obs {i}", [])
    recent = storage.get_recent(limit=3)
    assert len(recent) == 3


def test_get_by_id_missing(temp_db):
    assert storage.get_by_id(9999) is None


def test_empty_entities_list(temp_db):
    obs_id = storage.save_observation("testo senza entità", [])
    retrieved = storage.get_by_id(obs_id)
    assert retrieved["entities"] == []


def test_wal_mode_enabled(tmp_path, monkeypatch):
    """DB should use WAL journal mode after init_db."""
    import app.storage as storage_mod
    monkeypatch.setattr(storage_mod, "DB_PATH", tmp_path / "test.db")
    storage_mod.init_db()
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


from app.storage import save_synthesis, get_synthesis, save_enrichment, get_enrichment, find_observations_with_entity


def test_save_and_get_synthesis(temp_db):
    obs_id = storage.save_observation("testo", [])
    save_synthesis(obs_id, "Profilo: soggetto tech.", "qwen2.5:9b")
    result = get_synthesis(obs_id)
    assert result is not None
    text, model = result
    assert text == "Profilo: soggetto tech."
    assert model == "qwen2.5:9b"


def test_get_synthesis_none_when_absent(temp_db):
    obs_id = storage.save_observation("testo", [])
    assert get_synthesis(obs_id) is None


def test_save_and_get_enrichment(temp_db):
    obs_id = storage.save_observation("testo", [])
    data = {"8.8.8.8": {"country": "USA", "city": "Mountain View"}}
    save_enrichment(obs_id, data)
    result = get_enrichment(obs_id)
    assert result["8.8.8.8"]["country"] == "USA"


def test_get_enrichment_empty_when_absent(temp_db):
    obs_id = storage.save_observation("testo", [])
    assert get_enrichment(obs_id) == {}


def test_find_observations_with_entity(temp_db):
    from app.models import Entity
    e = Entity(type="email", value="mario@example.com", confidence="medium")
    obs_id = storage.save_observation("mario@example.com", [e])
    results = find_observations_with_entity("mario@example.com")
    assert any(r["id"] == obs_id for r in results)
