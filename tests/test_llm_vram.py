"""TDD handoff VRAM lato POE-OSINT.

Copre l'unload del modello dalla VRAM (`MLXBackend.unload()` + no-op di default
sulla base) e gli endpoint locali di orchestrazione `/admin/llm/unload` e
`/admin/llm/warm` che l'hub vocale chiama per cedere/riprendere la VRAM.
Nessun modello reale caricato: backend fake iniettato in `app.state`.
"""
from fastapi.testclient import TestClient

from app.llm.base import LLMBackend
from app.llm.mlx_backend import MLXBackend
from app.main import app


class _FakeBackend(LLMBackend):
    def __init__(self) -> None:
        self.unloaded = False
        self._avail = True

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def generate(self, prompt: str, system: str = "") -> str:
        return "x"

    async def is_available(self) -> bool:
        return self._avail

    def unload(self) -> None:
        self.unloaded = True


def test_mlx_unload_drops_model():
    b = MLXBackend("dummy/model")
    b._model = object()
    b._tok = object()
    b.unload()
    assert b._model is None
    assert b._tok is None


def test_base_unload_is_noop():
    class _Min(LLMBackend):
        @property
        def model_name(self) -> str:
            return "m"

        async def generate(self, prompt: str, system: str = "") -> str:
            return ""

        async def is_available(self) -> bool:
            return True

    assert _Min().unload() is None  # default no-op, non solleva


def test_admin_llm_unload_endpoint():
    with TestClient(app) as c:
        fake = _FakeBackend()
        app.state.llm_backend = fake
        r = c.post("/admin/llm/unload")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert fake.unloaded is True


def test_admin_llm_warm_endpoint():
    with TestClient(app) as c:
        fake = _FakeBackend()
        app.state.llm_backend = fake
        r = c.post("/admin/llm/warm")
        assert r.status_code == 200
        assert r.json()["ok"] is True
