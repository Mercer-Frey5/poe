"""Flush DB (testing) + validazione LLM degli IOC a bassa confidenza (background)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app import storage
from app.main import app, _validate_low_entities
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "vl.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_admin_reset_empties_db(client):
    storage.save_observation("x", [Entity("email", "a@b.com")])
    r = client.post("/admin/reset")
    assert r.status_code == 200
    assert r.headers.get("HX-Redirect") == "/"
    assert storage.get_recent(limit=10) == []


@pytest.mark.asyncio
async def test_validate_low_drops_fp(temp_db):
    obs_id = storage.save_observation("t", [
        Entity("person_name", "Connessioni", confidence="low"),
        Entity("person_name", "Mario Rossi", confidence="low"),
        Entity("email", "a@b.com", confidence="medium"),
    ])
    app_mock = MagicMock()
    app_mock.state.llm_backend.is_available = AsyncMock(return_value=True)
    app_mock.state.llm_backend.generate = AsyncMock(return_value='{"drop": ["Connessioni"]}')
    await _validate_low_entities(app_mock, obs_id)
    vals = [e["value"] for e in storage.get_by_id(obs_id)["entities"]]
    assert "Connessioni" not in vals       # FP droppato
    assert "Mario Rossi" in vals           # nome vero tenuto
    assert "a@b.com" in vals               # non-low intatto
