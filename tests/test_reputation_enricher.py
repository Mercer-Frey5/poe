"""Task 5: ReputationEnricher — lookup locale, no rete."""
import pytest
from app.reputation import store
from app.enrichers.reputation_enricher import ReputationEnricher
from app.models import Entity


@pytest.fixture
def temp_rep(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "REP_DB_PATH", tmp_path / "reputation.db")
    store.init_rep_db()


@pytest.mark.asyncio
async def test_enrich_flags_known_malicious(temp_rep):
    store.replace_source("threatfox", [
        {"value": "9.9.9.9", "type": "ipv4", "threat": "Cobalt Strike", "reference": "http://ref"},
    ])
    out = await ReputationEnricher().enrich(Entity("ipv4", "9.9.9.9"))
    rep = out.metadata["reputation"]
    assert rep["malicious"] is True
    assert "threatfox" in rep["sources"]
    assert rep["threat"] == "Cobalt Strike"


@pytest.mark.asyncio
async def test_enrich_noop_on_clean(temp_rep):
    out = await ReputationEnricher().enrich(Entity("ipv4", "1.1.1.1"))
    assert "reputation" not in out.metadata


@pytest.mark.asyncio
async def test_enrich_uses_most_recent_updated_at(temp_rep):
    store.replace_source("threatfox", [
        {"value": "9.9.9.9", "type": "ipv4", "threat": "Cobalt Strike", "reference": "http://ref"},
    ])
    store.replace_source("urlhaus", [
        {"value": "9.9.9.9", "type": "ipv4", "threat": "Malware", "reference": "http://ref2"},
    ])
    with store._connect() as conn:
        conn.execute(
            "UPDATE reputation SET updated_at=? WHERE source=?",
            ("2025-01-01T00:00:00", "threatfox"),
        )
        conn.execute(
            "UPDATE reputation SET updated_at=? WHERE source=?",
            ("2026-01-01T00:00:00", "urlhaus"),
        )
    out = await ReputationEnricher().enrich(Entity("ipv4", "9.9.9.9"))
    rep = out.metadata["reputation"]
    assert rep["updated_at"] == "2026-01-01T00:00:00"


@pytest.mark.asyncio
async def test_enrich_single_hit_updated_at_no_regression(temp_rep):
    store.replace_source("threatfox", [
        {"value": "9.9.9.9", "type": "ipv4", "threat": "Cobalt Strike", "reference": "http://ref"},
    ])
    out = await ReputationEnricher().enrich(Entity("ipv4", "9.9.9.9"))
    rep = out.metadata["reputation"]
    assert rep["malicious"] is True
    assert rep["sources"] == ["threatfox"]
    assert rep["threat"] == "Cobalt Strike"
    assert rep["updated_at"] is not None


def test_can_enrich_types():
    e = ReputationEnricher()
    assert e.can_enrich(Entity("ipv4", "8.8.8.8")) is True
    assert e.can_enrich(Entity("domain", "x.com")) is True
    assert e.can_enrich(Entity("hash_sha256", "abc")) is True
    assert e.can_enrich(Entity("person_name", "Mario")) is False


@pytest.mark.asyncio
async def test_enrich_includes_per_source_hits_breakdown(temp_rep):
    """L'espansione della entity-card vuole il dettaglio per singola fonte
    (non solo i campi aggregati): ogni hit mantiene il proprio threat/
    reference/updated_at, senza perdere informazione nell'aggregazione."""
    store.replace_source("threatfox", [
        {"value": "9.9.9.9", "type": "ipv4", "threat": "Cobalt Strike", "reference": "http://tf/ref"},
    ])
    store.replace_source("urlhaus", [
        {"value": "9.9.9.9", "type": "ipv4", "threat": "Emotet", "reference": "http://uh/ref"},
    ])
    out = await ReputationEnricher().enrich(Entity("ipv4", "9.9.9.9"))
    rep = out.metadata["reputation"]
    assert len(rep["hits"]) == 2
    by_source = {h["source"]: h for h in rep["hits"]}
    assert by_source["threatfox"]["threat"] == "Cobalt Strike"
    assert by_source["threatfox"]["reference"] == "http://tf/ref"
    assert by_source["urlhaus"]["threat"] == "Emotet"
    assert by_source["urlhaus"]["reference"] == "http://uh/ref"
