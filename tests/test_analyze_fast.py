"""Task 1: /analyze deterministico — niente LLM nel percorso critico."""
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
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "fast.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        app.state.recognizer = _FakeRecognizer()
        app.state.llm_backend = MagicMock()
        app.state.llm_extractor = MagicMock()
        app.state.llm_extractor.async_extract = AsyncMock(return_value=[])
        app.state.enricher_registry = MagicMock()
        app.state.enricher_registry.enrich_all = AsyncMock(side_effect=lambda ents, **k: ents)
        yield c


def test_analyze_does_not_call_llm_extractor(client):
    r = client.post("/analyze", data={"text": "scrivi a mario.rossi@example.com"})
    assert r.status_code == 200
    app.state.llm_extractor.async_extract.assert_not_called()


def test_email_only_input_yields_no_address(client):
    r = client.post("/analyze", data={"text": "contatto: mario.rossi@example.com"})
    assert r.status_code == 200
    assert "via roma" not in r.text.lower()
