import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app import storage
from app.main import app, _build_synthesis_prompt, _LIVE_LOOKUP_CACHE
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
        app.state.enricher_registry.enrich_all = AsyncMock(side_effect=lambda ents, **k: ents)
        yield client


def _obs_id(test_client) -> int:
    test_client.post("/analyze", data={"text": "mario.rossi@example.com 8.8.8.8"})
    return storage.get_recent(limit=1)[0]["id"]


def test_synthesis_404_unknown_obs(test_client):
    resp = test_client.post("/e/99999/synthesis")
    assert resp.status_code == 404


def test_synthesis_503_when_llm_offline(test_client):
    obs_id = _obs_id(test_client)
    with patch.object(app.state.llm_backend, "is_available", new=AsyncMock(return_value=False)):
        resp = test_client.post(f"/e/{obs_id}/synthesis")
    assert resp.status_code == 503
    assert "non disponibile" in resp.text.lower()


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


# ── Gate: la Sintesi appare solo con più di un IOC, sia in detail sia in Osserva ──

def test_synthesis_hidden_for_single_ioc(test_client):
    """Un solo IOC → niente pannello Sintesi (basta l'Analisi AI per-entità)."""
    from app.models import Entity
    oid = storage.save_observation("solo uno", [Entity("ipv4", "8.8.8.8")])
    html = test_client.get(f"/e/{oid}").text
    assert "Genera sintesi investigativa" not in html
    assert 'id="synthesis-panel"' not in html


def test_synthesis_shown_for_multi_ioc(test_client):
    """Più di un IOC → pannello Sintesi disponibile nell'osservazione salvata."""
    from app.models import Entity
    oid = storage.save_observation(
        "due ioc", [Entity("ipv4", "8.8.8.8"), Entity("domain", "example.com")]
    )
    html = test_client.get(f"/e/{oid}").text
    assert "Genera sintesi investigativa" in html
    assert 'id="synthesis-panel"' in html


def test_synthesis_available_in_analyze_preview(test_client):
    """L'anteprima 'Osserva' (POST /analyze) espone la Sintesi con >1 IOC."""
    resp = test_client.post("/analyze", data={"text": "mario.rossi@example.com 8.8.8.8"})
    assert resp.status_code == 200
    assert "Genera sintesi investigativa" in resp.text


def test_synthesis_hidden_in_analyze_preview_single_ioc(test_client):
    """Un solo IOC in anteprima 'Osserva' → niente Sintesi."""
    resp = test_client.post("/analyze", data={"text": "8.8.8.8"})
    assert resp.status_code == 200
    assert "Genera sintesi investigativa" not in resp.text


def test_enrich_route_404_unknown_obs(test_client):
    resp = test_client.post("/e/99999/enrich/ipv4/8.8.8.8")
    assert resp.status_code == 404


# ── _build_synthesis_prompt: deve includere i dati raw, non solo type/value ──
# Bug reale: il LLM diceva "dati insufficienti" per posizione/nazionalità
# nonostante geo/whois/ASN/AbuseIPDB/VirusTotal fossero già tutti disponibili
# — perché il prompt scartava tutto tranne type/value/confidence.

def test_synthesis_prompt_includes_entity_metadata():
    entities = [{
        "type": "ipv4", "value": "132.144.1.4", "confidence": "medium",
        "metadata": {"country": "United States", "city": "Fort Meade", "isp": "DoD Network Information Center"},
    }]
    user, _ = _build_synthesis_prompt("raw text", entities)
    assert "Fort Meade" in user
    assert "DoD Network Information Center" in user


def test_synthesis_prompt_includes_cached_live_lookup_raw_data():
    _LIVE_LOOKUP_CACHE.clear()
    _LIVE_LOOKUP_CACHE[(42, "site-abuseipdb", "132.144.1.4")] = {
        "ok": True, "abuse_score": 0, "usage_type": "Government",
    }
    entities = [{"type": "ipv4", "value": "132.144.1.4", "confidence": "medium", "metadata": {}}]
    user, _ = _build_synthesis_prompt("raw text", entities, observation_id=42)
    _LIVE_LOOKUP_CACHE.clear()
    assert "AbuseIPDB" in user
    assert "Government" in user
