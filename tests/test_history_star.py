"""Task 8: stella Preferiti per voce in Osservazioni recenti."""
import pytest
from fastapi.testclient import TestClient
from app import storage
from app.main import app
from app.extractors.regex_extractor import RegexExtractor


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "star.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    class _Rec:
        def recognize(self, text): return RegexExtractor().extract(text)
    with TestClient(app, raise_server_exceptions=True) as c:
        app.state.recognizer = _Rec()
        yield c


def test_recent_item_has_star_toggle(client):
    obs_id = storage.save_observation("test a@b.com", [])
    r = client.get("/history?view=all")
    assert r.status_code == 200
    assert f'hx-post="/e/{obs_id}/keep"' in r.text
