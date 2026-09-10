"""Test per service_health.py — reachability del SITO pubblico di un
servizio (mai l'endpoint API a pagamento), con cache in memoria per non
moltiplicare le richieste ad ogni poll della status bar (30s)."""
import httpx
import pytest
import respx

from app import service_health
from app.service_health import site_reachability


@pytest.fixture(autouse=True)
def _clear_cache():
    service_health._cache.clear()
    yield
    service_health._cache.clear()


@pytest.mark.asyncio
@respx.mock
async def test_site_reachability_fast_200_is_online():
    respx.head("https://example.test/").mock(return_value=httpx.Response(200))
    assert await site_reachability("https://example.test/") == "online"


@pytest.mark.asyncio
@respx.mock
async def test_site_reachability_500_is_offline():
    respx.head("https://example.test/").mock(return_value=httpx.Response(503))
    assert await site_reachability("https://example.test/") == "offline"


@pytest.mark.asyncio
@respx.mock
async def test_site_reachability_head_unsupported_falls_back_to_get():
    respx.head("https://example.test/").mock(return_value=httpx.Response(405))
    respx.get("https://example.test/").mock(return_value=httpx.Response(200))
    assert await site_reachability("https://example.test/") == "online"


@pytest.mark.asyncio
@respx.mock
async def test_site_reachability_fast_client_error_is_online():
    """Un 4xx (403/404/...) che risponde VELOCE prova che il server è vivo:
    ci sta solo rifiutando la richiesta (WAF/bot-block), non è "giù" né
    "lento". Bug reale: AbuseIPDB risponde 403 in ~0.1s a un ping automatico
    (blocco bot), ma veniva mostrato giallo/slow anche se sito e API
    funzionano benissimo."""
    respx.head("https://example.test/").mock(return_value=httpx.Response(403))
    respx.get("https://example.test/").mock(return_value=httpx.Response(403))
    assert await site_reachability("https://example.test/") == "online"




@pytest.mark.asyncio
async def test_site_reachability_network_error_is_offline(monkeypatch):
    async def _boom(self, *a, **k):
        raise httpx.ConnectError("boom")
    monkeypatch.setattr(httpx.AsyncClient, "head", _boom)
    assert await site_reachability("https://example.test/") == "offline"


@pytest.mark.asyncio
@respx.mock
async def test_site_reachability_is_cached_between_calls():
    route = respx.head("https://example.test/").mock(return_value=httpx.Response(200))
    await site_reachability("https://example.test/")
    await site_reachability("https://example.test/")
    assert route.call_count == 1  # seconda chiamata servita dalla cache


@pytest.mark.asyncio
@respx.mock
async def test_site_reachability_cache_expires(monkeypatch):
    route = respx.head("https://example.test/").mock(return_value=httpx.Response(200))
    await site_reachability("https://example.test/")
    monkeypatch.setattr(service_health, "_CACHE_TTL", -1)  # scaduta subito
    await site_reachability("https://example.test/")
    assert route.call_count == 2
