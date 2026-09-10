"""Task 2: badge di rischio nel render (card + riepilogo header)."""
import pytest
from fastapi.testclient import TestClient
from app import storage
from app.main import app
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "risk.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_critico_badge_and_header_summary(client):
    ent = Entity("ipv4", "9.9.9.9",
                 metadata={"reputation": {"malicious": True, "sources": ["threatfox"],
                                          "threat": "Cobalt Strike", "reference": "http://ref"}})
    oid = storage.save_observation("x", [ent])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert "risk-letter-critico" in r.text
    assert "MALEVOLO" in r.text
    assert "risk-summary" in r.text


def test_no_risk_badge_when_clean(client):
    oid = storage.save_observation("y", [Entity("ipv4", "1.1.1.1")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert "risk-letter" not in r.text
    assert "risk-summary" not in r.text


def test_risk_tooltip_humanizes_factors(client):
    """Fix 2c: il tooltip 'Rischio: LEVEL' non deve mostrare i token grezzi
    (reputation:threatfox, tld_sospetto) ma una spiegazione leggibile."""
    ent = Entity("domain", "evil.xyz",
                 metadata={"suspicious_tld": True,
                           "reputation": {"malicious": True, "sources": ["threatfox"]}})
    oid = storage.save_observation("z", [ent])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert "reputation:threatfox" not in r.text
    assert "tld_sospetto" not in r.text
    assert "presente in feed di minaccia" in r.text
    assert "TLD" in r.text
