"""Task 4: updater — refresh solo dei feed stale, downloader mockato (no rete)."""
import pytest
from app.reputation import store, updater
from app.reputation import feeds as feeds_mod


@pytest.fixture
def temp_rep(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "REP_DB_PATH", tmp_path / "reputation.db")
    store.init_rep_db()


_FEODO_ONLY = [{"name": "feodo", "url": "x", "format": "feodo_json", "ttl_hours": 12, "full": False}]


@pytest.mark.asyncio
async def test_refresh_downloads_and_stores(temp_rep, monkeypatch):
    monkeypatch.setattr(feeds_mod, "load_feeds", lambda: _FEODO_ONLY)
    async def fake_dl(url):
        return '[{"ip_address": "5.5.5.5", "malware": "Dridex"}]'
    res = await updater.refresh_stale(force=True, downloader=fake_dl)
    assert res["feodo"].startswith("updated")
    assert len(store.lookup("5.5.5.5")) == 1


@pytest.mark.asyncio
async def test_refresh_skips_fresh(temp_rep, monkeypatch):
    store.replace_source("feodo", [{"value": "5.5.5.5", "type": "ipv4"}])  # appena aggiornato
    monkeypatch.setattr(feeds_mod, "load_feeds", lambda: _FEODO_ONLY)
    called = {"n": 0}
    async def fake_dl(url):
        called["n"] += 1
        return "[]"
    res = await updater.refresh_stale(force=False, downloader=fake_dl)
    assert res["feodo"] == "fresh"
    assert called["n"] == 0            # nessun download perché non stale


@pytest.mark.asyncio
async def test_refresh_handles_download_error(temp_rep, monkeypatch):
    monkeypatch.setattr(feeds_mod, "load_feeds", lambda: _FEODO_ONLY)
    async def boom(url):
        raise RuntimeError("net down")
    res = await updater.refresh_stale(force=True, downloader=boom)
    assert res["feodo"] == "error"     # non solleva
