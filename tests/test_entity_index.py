"""Task 1-2: entity_index — schema + sync alle mutazioni."""
import pytest
from app import storage
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "idx.db")
    storage.init_db()


def _index_rows(observation_id=None):
    with storage._connect() as c:
        if observation_id is None:
            rows = c.execute("SELECT value, type, observation_id FROM entity_index").fetchall()
        else:
            rows = c.execute(
                "SELECT value, type, observation_id FROM entity_index WHERE observation_id=?",
                (observation_id,),
            ).fetchall()
    return {(r["value"], r["type"], r["observation_id"]) for r in rows}


def test_entity_index_table_exists(temp_db):
    with storage._connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(entity_index)").fetchall()}
    assert cols == {"value", "type", "observation_id"}


def test_save_observation_populates_index(temp_db):
    oid = storage.save_observation("x", [Entity("email", "a@b.com"), Entity("ipv4", "8.8.8.8")])
    assert _index_rows(oid) == {("a@b.com", "email", oid), ("8.8.8.8", "ipv4", oid)}


def test_rebuild_index_from_observations(temp_db):
    oid = storage.save_observation("x", [Entity("email", "a@b.com")])
    with storage._connect() as c:      # sporca l'index a mano
        c.execute("DELETE FROM entity_index")
    assert _index_rows() == set()
    storage.rebuild_index()
    assert _index_rows() == {("a@b.com", "email", oid)}


def test_add_entities_updates_index(temp_db):
    oid = storage.save_observation("x", [Entity("email", "a@b.com")])
    storage.add_entities(oid, [Entity("domain", "evil.com")])
    assert ("evil.com", "domain", oid) in _index_rows(oid)


def test_add_entities_dedup_ignores_whitespace_and_trailing_punctuation(temp_db):
    """LLM extractor e regex_extractor estraggono entrambi type=address dallo
    stesso testo con formattazione leggermente diversa (spazi doppi, punto
    finale) — l'exact-match su (type, value) da solo li vede come 2 entità
    diverse. Normalizza la CHIAVE di confronto (non il valore salvato)."""
    oid = storage.save_observation("x", [
        Entity("address", "via roma 1, 20100 milano", metadata={"extractor": "regex"}),
    ])
    storage.add_entities(oid, [
        Entity("address", "via roma  1, 20100 milano.", metadata={"extractor": "llm"}),
    ])
    addresses = [e for e in storage.get_by_id(oid)["entities"] if e["type"] == "address"]
    assert len(addresses) == 1
    # Il valore originale (regex, arrivato prima) resta quello salvato.
    assert addresses[0]["value"] == "via roma 1, 20100 milano"


def test_add_entities_dedup_still_treats_different_values_as_distinct(temp_db):
    """Non deve diventare fuzzy matching: solo whitespace/punteggiatura
    marginale sono ignorati, non testo effettivamente diverso."""
    oid = storage.save_observation("x", [Entity("address", "via roma 1, 20100 milano")])
    storage.add_entities(oid, [Entity("address", "via torino 5, 10100 torino")])
    addresses = [e for e in storage.get_by_id(oid)["entities"] if e["type"] == "address"]
    assert len(addresses) == 2


def test_remove_entity_updates_index(temp_db):
    oid = storage.save_observation("x", [Entity("email", "a@b.com"), Entity("ipv4", "8.8.8.8")])
    storage.remove_entity(oid, "ipv4", "8.8.8.8")
    assert _index_rows(oid) == {("a@b.com", "email", oid)}


def test_delete_observation_clears_index(temp_db):
    oid = storage.save_observation("x", [Entity("email", "a@b.com")])
    storage.delete_observation(oid)
    assert _index_rows(oid) == set()


def test_reset_db_clears_index(temp_db):
    storage.save_observation("x", [Entity("email", "a@b.com")])
    storage.reset_db()
    assert _index_rows() == set()
