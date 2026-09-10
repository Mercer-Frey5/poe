"""Task 2: export .md arricchito + nuovo export .json."""
import json
import pytest
from fastapi.testclient import TestClient
from app import storage
from app.main import app
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "export.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_export_md_enriched_with_risk_and_reputation(client):
    ent = Entity("ipv4", "9.9.9.9",
                 metadata={"reputation": {"malicious": True, "sources": ["threatfox"], "threat": "Cobalt Strike"}})
    oid = storage.save_observation("x", [ent])
    r = client.get(f"/e/{oid}/export.md")
    assert r.status_code == 200
    assert "[rischio: critico]" in r.text
    assert "⚠ malevolo" in r.text


def test_export_md_404_on_missing(client):
    assert client.get("/e/99999/export.md").status_code == 404


def test_export_json_full_structure(client):
    oid = storage.save_observation("x", [Entity("ipv4", "1.1.1.1")])
    r = client.get(f"/e/{oid}/export.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    data = json.loads(r.text)
    assert data["id"] == oid
    assert data["entities"][0]["value"] == "1.1.1.1"
    assert "risk" in data["entities"][0]
    assert "pivot" in data["entities"][0]


def test_export_json_404_on_missing(client):
    assert client.get("/e/99999/export.json").status_code == 404


def test_export_json_pivot_excludes_current_observation(client):
    storage.save_observation("prima", [Entity("ipv4", "8.8.8.8")])
    oid2 = storage.save_observation("seconda", [Entity("ipv4", "8.8.8.8")])
    r = client.get(f"/e/{oid2}/export.json")
    data = json.loads(r.text)
    pivot = data["entities"][0]["pivot"]
    assert pivot["count"] == 2
    assert oid2 not in pivot["other_observation_ids"]
