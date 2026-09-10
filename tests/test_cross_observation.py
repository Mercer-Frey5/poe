import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app import storage
from app.main import app
from app.extractors.regex_extractor import RegexExtractor


class _FakeRecognizer:
    def recognize(self, text: str):
        return RegexExtractor().extract(text)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_cross.db"
    monkeypatch.setattr(storage, "DB_PATH", db_file)
    storage.init_db()
    return db_file


@pytest.fixture
def test_client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.recognizer = _FakeRecognizer()
        app.state.llm_backend = MagicMock()
        app.state.llm_backend.model_name = "fake-model"
        app.state.llm_backend.is_available = AsyncMock(return_value=False)
        app.state.llm_extractor = MagicMock()
        app.state.llm_extractor.async_extract = AsyncMock(return_value=[])
        app.state.enricher_registry = MagicMock()
        app.state.enricher_registry.enrich_on_demand = AsyncMock(return_value=[])
        yield client


def test_cross_observation_finds_entity(test_client):
    test_client.post("/analyze", data={"text": "Contatto: target@example.com"})
    test_client.post("/analyze", data={"text": "Email: target@example.com info"})
    resp = test_client.get("/e/cross/target@example.com")
    assert resp.status_code == 200
    assert "target@example.com" in resp.text


def test_cross_observation_empty_for_unknown(test_client):
    resp = test_client.get("/e/cross/nobody@nowhere.xyz.invalid")
    assert resp.status_code == 200
