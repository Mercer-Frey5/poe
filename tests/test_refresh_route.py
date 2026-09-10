"""Test per POST /e/{id}/refresh — ricontrolla (re-enrich) tutte le entità
di un'osservazione salvata (reputation/geo/WHOIS possono essere cambiati
da quando è stata analizzata)."""
import pytest
from fastapi.testclient import TestClient
from app import storage
from app.reputation import store as rep_store
from app.main import app
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "obs.db")
    monkeypatch.setattr(rep_store, "REP_DB_PATH", tmp_path / "rep.db")
    storage.init_db()
    rep_store.init_rep_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# Entità di test: IP marcato bogon così sia IPEnricher (geo batch) che
# WHOISEnricher (RDAP) lo skippano strutturalmente (entrambi controllano
# metadata['bogon'] prima di fare qualunque chiamata di rete) — enrich_all()
# gira quindi 100% in locale, zero rete, zero flakiness da timeout condiviso.
# ReputationEnricher non guarda affatto il bogon: il lookup funziona lo stesso.
_BOGON_IP = "192.168.1.1"


def test_refresh_picks_up_new_reputation_match(client):
    # Nessuna metadata di reputation al momento del salvataggio: l'IOC non era
    # ancora noto come malevolo quando l'osservazione è stata analizzata.
    ent = Entity("ipv4", _BOGON_IP, metadata={"bogon": True})
    oid = storage.save_observation("x", [ent])

    # Il feed reputation viene aggiornato DOPO l'analisi originale: ora un
    # lookup su questo valore combacia.
    rep_store.replace_source("threatfox", [{
        "value": _BOGON_IP, "type": "ipv4", "source": "threatfox",
        "threat": "test", "reference": None, "updated_at": "2026-01-01",
    }])

    r = client.post(f"/e/{oid}/refresh")
    assert r.status_code == 200
    # v0.6.2: niente più badge "malevolo" a parte — un match reputation mostra
    # il badge di rischio (fallback a critico: bogon azzera solo il punteggio
    # numerico, non nasconde un match di threat-intelligence noto).
    assert "risk-letter-critico" in r.text
    assert "threat-intelligence" in r.text


def test_refresh_keeps_export_button(client):
    ent = Entity("ipv4", _BOGON_IP, metadata={"bogon": True})
    oid = storage.save_observation("x", [ent])

    r = client.post(f"/e/{oid}/refresh")
    assert r.status_code == 200
    assert "export-btn" in r.text


def test_refresh_404_on_missing(client):
    r = client.post("/e/99999/refresh")
    assert r.status_code == 404
