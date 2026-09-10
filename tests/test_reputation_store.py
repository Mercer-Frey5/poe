"""Task 1: reputation store (SQLite separato)."""
from datetime import datetime, timezone, timedelta
import pytest
from app.reputation import store


@pytest.fixture
def temp_rep(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "REP_DB_PATH", tmp_path / "reputation.db")
    store.init_rep_db()


def test_replace_source_and_lookup(temp_rep):
    store.replace_source("threatfox", [
        {"value": "8.8.8.8", "type": "ipv4", "threat": "CobaltStrike", "reference": "http://ref/1"},
    ])
    hits = store.lookup("8.8.8.8")
    assert len(hits) == 1
    assert hits[0]["source"] == "threatfox"
    assert hits[0]["threat"] == "CobaltStrike"
    assert store.lookup("1.1.1.1") == []


def test_replace_source_is_idempotent_per_source(temp_rep):
    store.replace_source("feodo", [{"value": "9.9.9.9", "type": "ipv4"}])
    store.replace_source("feodo", [{"value": "7.7.7.7", "type": "ipv4"}])  # sostituisce
    assert store.lookup("9.9.9.9") == []
    assert len(store.lookup("7.7.7.7")) == 1


def test_is_stale(temp_rep):
    assert store.is_stale("threatfox", 12) is True            # mai aggiornato
    store.replace_source("threatfox", [{"value": "8.8.8.8", "type": "ipv4"}])
    assert store.is_stale("threatfox", 12) is False           # appena aggiornato
    # forza updated_at vecchio
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    with store._connect() as c:
        c.execute("UPDATE feed_meta SET updated_at=? WHERE source=?", (old, "threatfox"))
    assert store.is_stale("threatfox", 12) is True


def test_feed_status(temp_rep):
    store.replace_source("feodo", [{"value": "9.9.9.9", "type": "ipv4"}])
    st = {s["source"]: s for s in store.feed_status()}
    assert st["feodo"]["rows"] == 1
