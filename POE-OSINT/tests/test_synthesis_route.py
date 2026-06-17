import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app import storage
from app.main import app
from app.extractors.regex_extractor import RegexExtractor


class _FakeRecognizer:
    def recognize(self, text: str):
        return RegexExtractor().extract(text)


class _FakeLLM:
    model_name = "fake-model"

    async def is_available(self):
        return False

    async def generate(self, prompt: str, system: str = "") -> str:
        return ""


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_synth.db"
    monkeypatch.setattr(storage, "DB_PATH", db_file)
    storage.init_db()
    return db_file


@pytest.fixture
def test_client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.recognizer = _FakeRecognizer()
        app.state.llm_backend = _FakeLLM()
        app.state.llm_extractor = MagicMock()
        app.state.llm_extractor.async_extract = AsyncMock(return_value=[])
        app.state.enricher_registry = MagicMock()
        app.state.enricher_registry.enrich_on_demand = AsyncMock(return_value=[])
        yield client


def _obs_id(test_client) -> int:
    test_client.post("/analyze", data={"text": "mario.rossi@example.com 8.8.8.8"})
    return storage.get_recent(limit=1)[0]["id"]


def test_synthesis_404_unknown_obs(test_client):
    resp = test_client.post("/e/99999/synthesis")
    assert resp.status_code == 404


def test_synthesis_503_when_ollama_offline(test_client):
    obs_id = _obs_id(test_client)
    with patch.object(app.state.llm_backend, "is_available", new=AsyncMock(return_value=False)):
        resp = test_client.post(f"/e/{obs_id}/synthesis")
    assert resp.status_code == 503
    assert "Ollama" in resp.text


def test_synthesis_generates_and_caches(test_client):
    obs_id = _obs_id(test_client)
    with (
        patch.object(app.state.llm_backend, "is_available", new=AsyncMock(return_value=True)),
        patch.object(app.state.llm_backend, "generate", new=AsyncMock(return_value="Soggetto tech.")),
    ):
        resp = test_client.post(f"/e/{obs_id}/synthesis")
        assert resp.status_code == 200
        assert "Soggetto tech." in resp.text

        # Second call uses cache — no generate call needed
        resp2 = test_client.post(f"/e/{obs_id}/synthesis")
        assert "Soggetto tech." in resp2.text


def test_enrich_route_404_unknown_obs(test_client):
    resp = test_client.post("/e/99999/enrich/ipv4/8.8.8.8")
    assert resp.status_code == 404
