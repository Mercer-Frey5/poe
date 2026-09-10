"""L'analisi AI di una entità deve vedere i dati RAW dei tool live (AbuseIPDB,
VirusTotal, Shodan, crt.sh, ecc.) già interrogati per quella entità/osservazione,
non solo il testo originale + l'enrichment geo/whois automatico. I lookup live
sono fetchati dal browser (nessuna persistenza) — /e/{id}/lookup/{resource}/{value}
li mette in una cache in-memory per-processo (_LIVE_LOOKUP_CACHE) così che
/entity-ai possa includerli nel prompt se sono già stati interrogati."""
import pytest
from fastapi.testclient import TestClient
from app import storage
from app.main import app, _LIVE_LOOKUP_CACHE, _build_entity_ai_prompt
from app.models import Entity


class _FakeLLM:
    model_name = "fake-model"

    async def is_available(self):
        return True

    async def generate(self, prompt: str, system: str = "") -> str:
        return "Analisi di test."


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "entity_ai_raw.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    _LIVE_LOOKUP_CACHE.clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        app.state.llm_backend = _FakeLLM()
        yield c
    _LIVE_LOOKUP_CACHE.clear()


async def _fake_abuseipdb_ok(ip):
    return {"ok": True, "abuse_score": 87, "total_reports": 12, "country": "CN"}


def test_live_lookup_route_caches_raw_result(client, monkeypatch):
    monkeypatch.setattr("app.main.abuseipdb_lookup", _fake_abuseipdb_ok)
    oid = storage.save_observation("x", [Entity("ipv4", "1.2.3.4")])
    client.post(f"/e/{oid}/lookup/site-abuseipdb/1.2.3.4")
    cached = _LIVE_LOOKUP_CACHE.get((oid, "site-abuseipdb", "1.2.3.4"))
    assert cached == {"ok": True, "abuse_score": 87, "total_reports": 12, "country": "CN"}


def test_entity_ai_prompt_includes_cached_live_lookup_raw_data(client, monkeypatch):
    """L'analisi AI, chiamata DOPO che un lookup live è stato eseguito per la
    stessa entità/osservazione, deve includere quel dato raw nel prompt."""
    monkeypatch.setattr("app.main.abuseipdb_lookup", _fake_abuseipdb_ok)
    oid = storage.save_observation("x", [Entity("ipv4", "1.2.3.4")])
    client.post(f"/e/{oid}/lookup/site-abuseipdb/1.2.3.4")

    captured = {}

    async def _capture_generate(prompt, system=""):
        captured["prompt"] = prompt
        return "Analisi di test."

    app.state.llm_backend.generate = _capture_generate
    r = client.post(f"/e/{oid}/entity-ai", data={"entity_type": "ipv4", "entity_value": "1.2.3.4"})
    assert r.status_code == 200
    assert "abuse_score" in captured["prompt"]
    assert "87" in captured["prompt"]


def test_build_entity_ai_prompt_appends_raw_live_results():
    user, _ = _build_entity_ai_prompt(
        "ipv4", "1.2.3.4", {}, "raw text here",
        live_results={"site-abuseipdb": {"ok": True, "abuse_score": 87}},
    )
    assert "abuse_score" in user
    assert "87" in user


def test_build_entity_ai_prompt_labels_blocks_with_human_source_name():
    """Ogni blocco raw deve essere etichettato col nome leggibile della fonte
    (dal catalogo, es. "AbuseIPDB") non l'id interno ("site-abuseipdb"): il
    LLM deve capire DA QUALE tool viene ogni dato, non solo vedere JSON nudo."""
    user, _ = _build_entity_ai_prompt(
        "ipv4", "1.2.3.4", {}, "raw text here",
        live_results={"site-abuseipdb": {"ok": True, "abuse_score": 87}},
    )
    assert "AbuseIPDB" in user
    assert "site-abuseipdb" not in user


def test_build_entity_ai_prompt_system_has_anti_hallucination_guardrails():
    """Il system prompt deve avvisare il LLM che le fonti hanno scale/schemi
    eterogenei e che ok:false/campi assenti significano 'dato non disponibile',
    non 'nessuna minaccia' — per evitare interpretazioni inventate dei dati raw."""
    _, system = _build_entity_ai_prompt("ipv4", "1.2.3.4", {}, "raw", live_results={})
    lowered = system.lower()
    assert "non inventare" in lowered
    assert "non disponibil" in lowered or "ok" in lowered


def test_build_entity_ai_prompt_no_live_results_still_works():
    user, _ = _build_entity_ai_prompt("ipv4", "1.2.3.4", {}, "raw text here", live_results={})
    assert "Entità: [ipv4] 1.2.3.4" in user


def test_build_entity_ai_prompt_passes_full_raw_metadata():
    """Il LLM deve vedere TUTTI i dati noti sull'entità in forma grezza (JSON),
    non un sottoinsieme curato/filtrato — anche campi come bogon/extractor
    prima esclusi, così l'analisi ha il quadro completo."""
    meta = {
        "country": "China", "isp": "Tencent Cloud", "org": "Tencent",
        "lat": 22.5, "lon": 114.0, "bogon": False, "extractor": "regex",
    }
    user, _ = _build_entity_ai_prompt("ipv4", "1.2.3.4", meta, "raw text here", live_results={})
    assert "Tencent Cloud" in user
    assert "22.5" in user
    assert "bogon" in user  # non più filtrato: dato raw completo
