"""Wrapper sottili sulle funzioni di POE-OSINT (app.*), indipendenti dal
framework MCP. Qui vive la logica: testabile senza stdio, riusata da server.py
(tool MCP) e da demo.py.

Nessuna funzione qui scrive sul DB, tocca segreti o carica l'LLM. Il confine di
tier è imposto a monte da permissions.py + server.py.
"""
from __future__ import annotations

from app import osint_catalog
from app.live_lookup import (
    codice_fiscale_lookup,
    crtsh_lookup,
    dorks_lookup,
    phone_info_lookup,
)
from app.reputation import store as reputation_store

MAX_INPUT_CHARS = 50_000

_recognizer = None


def _get_recognizer():
    """Costruisce (lazy) e cache-a il recognizer deterministico (regex + spaCy).
    Nei test si inietta uno stub per evitare il caricamento del modello."""
    global _recognizer
    if _recognizer is None:
        from app.extractors.regex_extractor import RegexExtractor
        from app.extractors.spacy_extractor import SpacyExtractor
        from app.recognizer import Recognizer
        _recognizer = Recognizer(RegexExtractor(), SpacyExtractor())
    return _recognizer


def analyze_text(text: str, recognizer=None) -> dict:
    """Estrazione entità DETERMINISTICA (no LLM, no DB, no rete). Rispecchia
    POST /api/analyze: strip, testo vuoto -> errore, >50k caratteri -> errore."""
    text = (text or "").strip()
    if not text:
        return {"error": "testo vuoto", "count": 0, "entities": []}
    if len(text) > MAX_INPUT_CHARS:
        return {"error": "input troppo lungo (>50k)", "count": 0, "entities": []}
    rec = recognizer if recognizer is not None else _get_recognizer()
    dicts = [e.to_dict() for e in rec.recognize(text)]
    return {"count": len(dicts), "entities": dicts}


async def codice_fiscale(cf: str) -> dict:
    return await codice_fiscale_lookup(cf)


async def phone_info(phone: str) -> dict:
    return await phone_info_lookup(phone)


async def dorks(value: str, kind: str = "email") -> dict:
    return await dorks_lookup(value, kind)


def catalog_resources(entity_type: str | None = None) -> dict:
    """Catalogo OSINT (lettura, dati di riferimento). Con entity_type filtra le
    risorse applicabili a quel tipo di IOC."""
    if entity_type:
        resources = osint_catalog.resources_for_type(entity_type)
    else:
        resources = osint_catalog.load_catalog()
    return {"ok": True, "count": len(resources), "resources": resources}


def reputation_lookup(value: str) -> dict:
    """Reputation IOC locale (feed pubblici in reputation.db, nessuna rete)."""
    try:
        hits = reputation_store.lookup(value)
    except Exception as exc:  # DB assente/corrotto: degrada in modo visibile
        return {"ok": False, "value": value, "error": f"reputation.db non disponibile: {exc}"}
    return {"ok": True, "value": value, "hits": hits}


async def crtsh(domain: str) -> dict:
    """LIVE_KEYLESS: Certificate Transparency (crt.sh). Trasmette solo il dominio
    interrogato. Idempotente, nessuna quota."""
    return await crtsh_lookup(domain)


def status() -> dict:
    from poe_mcp import permissions
    live = permissions.live_enabled()
    return {
        "server": "poe-osint",
        "version": "0.1.0",
        "transport": "stdio",
        "live": live,
        "tiers": [t.value for t in permissions.Tier],
        "tools_enabled": permissions.default_enabled_tool_names(live=live),
    }
