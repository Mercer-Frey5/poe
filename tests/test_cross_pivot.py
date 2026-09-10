"""Task 4: vista pivot /e/cross/{value}."""
import pytest
from fastapi.testclient import TestClient
from app import storage
from app.main import app
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "cross.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_cross_shows_observations_and_related(client):
    storage.save_observation("a", [Entity("ipv4", "8.8.8.8"), Entity("domain", "evil.com")])
    storage.save_observation("b", [Entity("ipv4", "8.8.8.8")])
    r = client.get("/e/cross/8.8.8.8")
    assert r.status_code == 200
    assert "evil.com" in r.text          # IOC correlato mostrato
    assert "8.8.8.8" in r.text            # header valore
