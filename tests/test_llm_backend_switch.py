"""Toggle LLM runtime: POST /admin/llm/backend cambia app.state.llm_backend
(Locale MLX <-> Claude abbonamento) senza riavvio, ricostruisce llm_extractor,
libera la VRAM del backend uscente e svuota la cache entity-ai. Scelta volatile."""
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app, _ENTITY_AI_CACHE
from app.llm.claude_backend import ClaudeCodeBackend


class _FakeMLX:
    """Sta al posto di MLXBackend: model_name + unload spia + is_available."""
    model_name = "mlx-fake"

    def __init__(self):
        self.unloaded = False

    def unload(self):
        self.unloaded = True

    async def is_available(self):
        return True


def test_switch_to_claude_sets_backend_extractor_and_unloads_old():
    with TestClient(app) as c, patch.object(
        ClaudeCodeBackend, "is_available", new=AsyncMock(return_value=True)
    ):
        fake = _FakeMLX()
        app.state.llm_backend = fake
        old_ext = app.state.llm_extractor
        r = c.post("/admin/llm/backend", data={"backend": "claude", "model": "sonnet"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] and body["backend"] == "claude" and body["model"] == "sonnet"
        assert body["kind"] == "claude"
        assert isinstance(app.state.llm_backend, ClaudeCodeBackend)
        assert "sonnet" in app.state.llm_backend.model_name
        assert app.state.llm_extractor is not old_ext        # extractor ricostruito
        assert fake.unloaded is True                          # VRAM del vecchio liberata


def test_switch_clears_entity_ai_cache():
    with TestClient(app) as c, patch.object(
        ClaudeCodeBackend, "is_available", new=AsyncMock(return_value=True)
    ):
        app.state.llm_backend = _FakeMLX()
        _ENTITY_AI_CACHE[(1, "ipv4", "8.8.8.8")] = "vecchia analisi"
        c.post("/admin/llm/backend", data={"backend": "claude", "model": "opus"})
        assert _ENTITY_AI_CACHE == {}


def test_switch_to_claude_unavailable_is_400_and_keeps_backend():
    with TestClient(app) as c, patch.object(
        ClaudeCodeBackend, "is_available", new=AsyncMock(return_value=False)
    ):
        fake = _FakeMLX()
        app.state.llm_backend = fake
        r = c.post("/admin/llm/backend", data={"backend": "claude", "model": "sonnet"})
        assert r.status_code == 400
        assert app.state.llm_backend is fake


def test_invalid_backend_is_400():
    with TestClient(app) as c:
        fake = _FakeMLX()
        app.state.llm_backend = fake
        r = c.post("/admin/llm/backend", data={"backend": "foo"})
        assert r.status_code == 400
        assert app.state.llm_backend is fake


def test_invalid_claude_model_is_400():
    with TestClient(app) as c, patch.object(
        ClaudeCodeBackend, "is_available", new=AsyncMock(return_value=True)
    ):
        fake = _FakeMLX()
        app.state.llm_backend = fake
        r = c.post("/admin/llm/backend", data={"backend": "claude", "model": "gpt4"})
        assert r.status_code == 400
        assert app.state.llm_backend is fake


def test_api_status_includes_kind_local():
    with TestClient(app) as c:
        app.state.llm_backend = _FakeMLX()
        d = c.get("/api/status").json()
        assert d["llm"]["kind"] == "local"


def test_kind_e_local_per_openai_compat_su_localhost(monkeypatch):
    """Un backend OpenAI-compatibile che punta a LM Studio sulla stessa
    macchina resta 'local': non deve allarmare per nulla."""
    from app.main import _llm_kind
    from app.llm.openai_backend import OpenAICompatBackend
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1", model="m")
    assert _llm_kind(b) == "local"


def test_kind_e_cloud_per_openai_compat_su_endpoint_pubblico():
    """Se l'utente lo punta a OpenRouter (o un altro servizio su Internet),
    la status bar deve dirlo: prima veniva mostrato come 'local', l'esatto
    contrario di quel che stava succedendo ai dati."""
    from app.main import _llm_kind
    from app.llm.openai_backend import OpenAICompatBackend
    b = OpenAICompatBackend(base_url="https://openrouter.ai/api/v1", model="m")
    assert _llm_kind(b) == "cloud"
