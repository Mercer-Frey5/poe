"""Task 6: badge malevolo nel render della card."""
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


def test_malicious_badge_in_detail(client):
    ent = Entity("ipv4", "9.9.9.9",
                 metadata={"reputation": {"malicious": True, "sources": ["threatfox"],
                                          "threat": "Cobalt Strike", "reference": "http://ref"}})
    oid = storage.save_observation("x", [ent])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    # v0.6.2: reputation malicious sempre porta a risk score 100 (peso
    # reputation_malicious) -> livello critico, badge lettera "C!" (non più
    # un badge "malevolo" a parte: confluisce nel tooltip del rischio).
    assert "risk-letter-critico" in r.text
    assert "Cobalt Strike" in r.text
    assert "threat-intelligence" in r.text
