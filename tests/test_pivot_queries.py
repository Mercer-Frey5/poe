"""Task 3: query di pivot sopra entity_index."""
import pytest
from app import storage
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "pivot.db")
    storage.init_db()


def test_observations_with_value(temp_db):
    o1 = storage.save_observation("a", [Entity("ipv4", "8.8.8.8"), Entity("email", "x@y.com")])
    o2 = storage.save_observation("b", [Entity("ipv4", "8.8.8.8")])
    storage.save_observation("c", [Entity("email", "z@y.com")])
    ids = [o["id"] for o in storage.observations_with_value("8.8.8.8")]
    assert set(ids) == {o1, o2}


def test_related_entities_cooccurrence(temp_db):
    storage.save_observation("a", [Entity("ipv4", "8.8.8.8"), Entity("email", "x@y.com")])
    storage.save_observation("b", [Entity("ipv4", "8.8.8.8"), Entity("domain", "evil.com")])
    rel = storage.related_entities("8.8.8.8")
    by_val = {r["value"]: r for r in rel}
    assert "8.8.8.8" not in by_val               # esclude sé stesso
    assert by_val["x@y.com"]["shared"] == 1
    assert by_val["evil.com"]["shared"] == 1
    assert by_val["x@y.com"]["type"] == "email"


def test_counts_for_values_batch(temp_db):
    storage.save_observation("a", [Entity("ipv4", "8.8.8.8")])
    storage.save_observation("b", [Entity("ipv4", "8.8.8.8"), Entity("email", "x@y.com")])
    counts = storage.counts_for_values(["8.8.8.8", "x@y.com", "nope"])
    assert counts["8.8.8.8"] == 2
    assert counts["x@y.com"] == 1
    assert "nope" not in counts


def test_counts_for_values_empty(temp_db):
    assert storage.counts_for_values([]) == {}


def test_ensure_index_rebuilds_when_empty(temp_db):
    oid = storage.save_observation("a", [Entity("ipv4", "8.8.8.8")])
    with storage._connect() as c:
        c.execute("DELETE FROM entity_index")
    storage.ensure_index()
    assert storage.counts_for_values(["8.8.8.8"]) == {"8.8.8.8": 1}
    assert [o["id"] for o in storage.observations_with_value("8.8.8.8")] == [oid]
