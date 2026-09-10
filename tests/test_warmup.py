"""Task 6: il warmup all'avvio non rompe il boot anche se il backend fallisce."""
from fastapi.testclient import TestClient
from app import storage
from app.main import app


def test_app_boots_even_if_warmup_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "warm.db")
    import app.main as main_mod

    class _BoomBackend:
        model_name = "boom"
        _model = None
        async def is_available(self):
            raise RuntimeError("no MLX here")
        async def generate(self, p, s=""):
            return ""

    monkeypatch.setattr(main_mod, "_make_llm_backend", lambda: _BoomBackend())
    with TestClient(app, raise_server_exceptions=True) as c:
        assert c.get("/health").status_code in (200, 503)
