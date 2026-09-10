"""GET /api/status — status bar 'Servizi': i tool/siti da tenere sotto
controllo. Leggero (nessun ping di rete a ogni poll di 30s) tranne per i
feed reputation, dove la freschezza si verifica in locale (reputation.db)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from app import storage
from app.reputation import store as rep_store
from app.main import app


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "obs.db")
    monkeypatch.setattr(rep_store, "REP_DB_PATH", tmp_path / "rep.db")
    storage.init_db()
    rep_store.init_rep_db()


@pytest.fixture(autouse=True)
def _fake_site_reachability(monkeypatch):
    """I servizi a chiave pingano il sito pubblico (site_reachability, vera
    chiamata di rete) — mockato di default per non colpire abuseipdb.com/
    virustotal.com/shodan.io ad ogni test. test_status_pings_key_gated_sites
    sovrascrive con la propria versione per verificare il wiring."""
    async def _fake(url):
        return "online"
    monkeypatch.setattr("app.main.site_reachability", _fake)


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_status_reports_all_expected_services(client):
    """Solo i servizi con un segnale di stato reale (niente voci sempre
    "online" senza un vero check dietro — troppi dot inutili in barra)."""
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    for key in ("llm", "reputation", "abuseipdb", "virustotal", "shodan"):
        assert key in data, f"manca '{key}' nella status bar"
        assert "name" in data[key] and "state" in data[key]


def test_status_pings_key_gated_sites_not_api(client, monkeypatch):
    """I servizi a chiave devono pingare il SITO pubblico (mai l'endpoint
    API a pagamento, per non consumare quota solo per un pallino di stato)."""
    calls = []

    async def _fake(url):
        calls.append(url)
        return "slow"
    monkeypatch.setattr("app.main.site_reachability", _fake)

    r = client.get("/api/status")
    data = r.json()
    for key in ("abuseipdb", "virustotal", "shodan"):
        assert data[key]["state"] == "slow"
    assert any("abuseipdb.com" in u for u in calls)
    assert any("virustotal.com" in u for u in calls)
    assert any("shodan.io" in u for u in calls)
    assert not any("api.abuseipdb.com" in u or "api/v3" in u or "api.shodan.io" in u for u in calls)


def test_reputation_status_offline_when_never_fetched(client):
    r = client.get("/api/status")
    assert r.json()["reputation"]["state"] == "offline"


def test_reputation_status_online_when_all_feeds_fresh(client):
    rep_store.replace_source("threatfox", [{"value": "1.1.1.1", "type": "ipv4"}])
    rep_store.replace_source("urlhaus", [{"value": "http://x", "type": "url"}])
    rep_store.replace_source("feodo", [{"value": "2.2.2.2", "type": "ipv4"}])
    rep_store.replace_source("malwarebazaar", [{"value": "aaaa", "type": "hash_sha256"}])
    rep_store.replace_source("blocklistde", [{"value": "3.3.3.3", "type": "ipv4"}])
    r = client.get("/api/status")
    assert r.json()["reputation"]["state"] == "online"


def test_reputation_status_slow_when_some_feeds_stale(client):
    rep_store.replace_source("threatfox", [{"value": "1.1.1.1", "type": "ipv4"}])
    rep_store.replace_source("urlhaus", [{"value": "http://x", "type": "url"}])
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="seconds")
    with rep_store._connect() as conn:
        conn.execute("UPDATE feed_meta SET updated_at=? WHERE source=?", (old, "urlhaus"))
    r = client.get("/api/status")
    assert r.json()["reputation"]["state"] == "slow"


def test_status_bar_markup_has_new_service_items(client):
    """La status bar (base.html) deve avere un data-svc per ogni chiave
    ritornata da /api/status, altrimenti il polling JS non trova l'elemento
    da aggiornare (nessun errore visibile, solo un dot che resta grigio)."""
    r = client.get("/")
    assert r.status_code == 200
    for svc in ("llm", "reputation", "abuseipdb", "virustotal", "shodan"):
        assert f'data-svc="{svc}"' in r.text
