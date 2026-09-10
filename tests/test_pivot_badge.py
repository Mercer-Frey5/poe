"""Task 5: badge pivot sulle card (N>=2 → link /e/cross)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app import storage
from app.main import app
from app.models import Entity
from app.extractors.regex_extractor import RegexExtractor


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "badge.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    class _Rec:
        def recognize(self, text): return RegexExtractor().extract(text)
    with TestClient(app, raise_server_exceptions=True) as c:
        app.state.recognizer = _Rec()
        app.state.enricher_registry = MagicMock()
        app.state.enricher_registry.enrich_all = AsyncMock(side_effect=lambda ents, **k: ents)
        yield c


def test_badge_shown_when_value_in_two_observations(client):
    storage.save_observation("prev", [Entity("ipv4", "8.8.8.8")])   # già presente altrove
    r = client.post("/analyze", data={"text": "vedi 8.8.8.8"})
    assert r.status_code == 200
    assert "/e/cross/8.8.8.8" in r.text        # badge link presente (N=2)


def test_no_badge_when_value_unique(client):
    r = client.post("/analyze", data={"text": "vedi 1.2.3.4"})
    assert r.status_code == 200
    assert "/e/cross/1.2.3.4" not in r.text     # N=1 → niente badge
