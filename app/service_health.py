"""service_health.py — reachability di servizi esterni per la status bar
"Servizi". Pinga il SITO pubblico, mai l'endpoint API a pagamento: le key
a quota limitata (AbuseIPDB/VirusTotal/Shodan) non devono essere consumate
solo per mostrare un pallino di stato. Risultato cache-ato in memoria per
qualche secondo: la status bar polla /api/status ogni 30s, più tab aperte
non devono moltiplicare le richieste in uscita."""
from __future__ import annotations

import time

import httpx

_TIMEOUT = 5.0
_CACHE_TTL = 25.0
_SLOW_THRESHOLD = 2.5

_cache: dict[str, tuple[float, str]] = {}

__all__ = ["site_reachability"]


async def site_reachability(url: str) -> str:
    """"online" (risponde rapido), "slow" (risponde ma lento o errore
    client), "offline" (timeout/errore di rete/errore server). Cache-ato
    per url per _CACHE_TTL secondi."""
    cached = _cache.get(url)
    now = time.monotonic()
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]
    state = await _ping(url)
    _cache[url] = (now, state)
    return state


async def _ping(url: str) -> str:
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.head(url)
            if resp.status_code >= 400:  # alcuni siti non supportano HEAD
                resp = await client.get(url)
        elapsed = time.monotonic() - t0
    except Exception:
        return "offline"
    if resp.status_code >= 500:
        return "offline"
    if elapsed > _SLOW_THRESHOLD:
        return "slow"
    # Un 4xx veloce (es. 403 da un WAF/bot-block, comune su AbuseIPDB) prova
    # che il server è vivo e risponde subito: è "online", non "slow" — ci sta
    # solo rifiutando QUESTA richiesta automatica, non è un sintomo di down.
    return "online"
