"""WHOIS/RDAP enricher.

- Domini/URL: `python-whois` (port-43), campi estesi.
- IP: RDAP via HTTP (`rdap.org`, httpx) — il WHOIS classico non copre gli IP.
Cache in-memory con TTL per ridurre il lag (le query WHOIS/RDAP sono lente).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime

import httpx
import whois

from app.enrichers.base import BaseEnricher
from app.models import Entity

logger = logging.getLogger(__name__)

__all__ = ["WHOISEnricher"]

_CACHE_TTL = 3600.0  # 1h
_CACHE: dict[str, tuple[float, dict]] = {}


def _fmt(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, list):
        d = d[0] if d else None
    if isinstance(d, (datetime, date)):
        return d.strftime("%Y-%m-%d")
    return str(d) if d else None


def _first(v):
    return (v[0] if v else None) if isinstance(v, list) else v


def _cache_get(key: str) -> dict | None:
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL:
        return hit[1]
    return None


def _cache_put(key: str, data: dict) -> None:
    _CACHE[key] = (time.time(), data)


def _whois_domain(domain: str) -> dict:
    r = whois.whois(domain)
    ns = r.name_servers or []
    return {
        "registrar": _first(r.registrar),
        "creation_date": _fmt(r.creation_date),
        "expiration_date": _fmt(r.expiration_date),
        "updated_date": _fmt(getattr(r, "updated_date", None)),
        "registrant_org": _first(r.org),
        "registrant_country": _first(getattr(r, "country", None)),
        "status": _first(getattr(r, "status", None)),
        "dnssec": _first(getattr(r, "dnssec", None)),
        "name_servers": list(ns)[:4] if ns else [],
    }


def _rdap_parse(data: dict) -> dict:
    """Estrae org + abuse dalle entities RDAP (vcardArray) + nome rete, paese, CIDR."""
    org = abuse = None
    for ent in data.get("entities", []) or []:
        roles = ent.get("roles") or []
        vcard = (ent.get("vcardArray") or [None, []])[1]
        fn = email = None
        for row in vcard:
            if not isinstance(row, list) or len(row) < 4:
                continue
            if row[0] == "fn":
                fn = row[3]
            elif row[0] == "email":
                email = row[3]
        if "abuse" in roles and email:
            abuse = email
        if ("registrant" in roles or "administrative" in roles) and fn and not org:
            org = fn
    cidr = None
    for c in data.get("cidr0_cidrs", []) or []:
        if c.get("v4prefix"):
            cidr = f"{c['v4prefix']}/{c.get('length')}"
            break
    if not cidr and data.get("startAddress"):
        cidr = f"{data.get('startAddress')} - {data.get('endAddress')}"
    return {
        "rdap_name": data.get("name"),
        "rdap_country": data.get("country"),
        "rdap_cidr": cidr,
        "rdap_org": org,
        "rdap_abuse": abuse,
    }


def _rdap_domain_parse(data: dict) -> dict:
    """Estrae i campi dominio da una risposta RDAP (rdap.org/domain/...)."""
    events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events", []) or []}

    def _date(key):
        v = events.get(key)
        return v[:10] if isinstance(v, str) and len(v) >= 10 else None

    registrar = None
    for ent in data.get("entities", []) or []:
        if "registrar" in (ent.get("roles") or []):
            vcard = (ent.get("vcardArray") or [None, []])[1]
            for row in vcard:
                if isinstance(row, list) and len(row) >= 4 and row[0] == "fn":
                    registrar = row[3]
                    break
    ns = [n.get("ldhName", "").lower() for n in data.get("nameservers", []) or [] if n.get("ldhName")]
    secure = data.get("secureDNS") or {}
    dnssec = "signed" if secure.get("delegationSigned") else "unsigned"
    return {
        "registrar": registrar,
        "creation_date": _date("registration"),
        "expiration_date": _date("expiration"),
        "updated_date": _date("last changed"),
        "status": ", ".join(data.get("status", []) or []) or None,
        "dnssec": dnssec,
        "name_servers": ns[:4],
    }


async def _rdap_domain(domain: str) -> dict:
    async with httpx.AsyncClient(
        timeout=6.0, headers={"Accept": "application/rdap+json"}
    ) as c:
        resp = await c.get(f"https://rdap.org/domain/{domain}", follow_redirects=True)
    resp.raise_for_status()
    return _rdap_domain_parse(resp.json())


async def _rdap_ip(ip: str) -> dict:
    async with httpx.AsyncClient(
        timeout=6.0, headers={"Accept": "application/rdap+json"}
    ) as c:
        resp = await c.get(f"https://rdap.org/ip/{ip}", follow_redirects=True)
    resp.raise_for_status()
    return _rdap_parse(resp.json())


async def _ripe_abuse_contact(ip: str) -> list[str]:
    """Abuse contact via RIPEstat (keyless, aggrega dal registro competente
    anche fuori regione RIPE). Complementare a rdap_abuse: a volte RDAP puro
    non espone un contatto abuse, RIPEstat sì (o viceversa). Idea presa da
    un tool WHOIS legacy fornito dall'Operatore."""
    async with httpx.AsyncClient(timeout=6.0) as c:
        resp = await c.get(
            "https://stat.ripe.net/data/abuse-contact-finder/data.json",
            params={"resource": ip},
        )
    resp.raise_for_status()
    return resp.json().get("data", {}).get("abuse_contacts", []) or []


class WHOISEnricher(BaseEnricher):
    def can_enrich(self, entity: Entity) -> bool:
        if entity.type in ("domain", "url"):
            return True
        if entity.type == "ipv4" and not entity.metadata.get("bogon"):
            return True
        return False

    async def enrich(self, entity: Entity) -> Entity:
        try:
            if entity.type == "ipv4":
                key = f"ip:{entity.value}"
                data = _cache_get(key)
                if data is None:
                    data = await _rdap_ip(entity.value)
                    try:
                        abuse_contacts = await _ripe_abuse_contact(entity.value)
                        if abuse_contacts:
                            data["ripe_abuse_contacts"] = ", ".join(abuse_contacts)
                    except Exception:
                        logger.warning("RIPE abuse-contact-finder: failed for %s", entity.value)
                    _cache_put(key, data)
            else:
                domain = entity.value
                if entity.type == "url":
                    from urllib.parse import urlparse
                    domain = urlparse(entity.value).hostname or entity.value
                key = f"dom:{domain}"
                data = _cache_get(key)
                if data is None:
                    # Solo RDAP (veloce, HTTP/JSON). Niente fallback python-whois
                    # porta-43: era lento e causava timeout in /analyze. I TLD non
                    # coperti da RDAP semplicemente non avranno WHOIS inline.
                    data = await _rdap_domain(domain)
                    _cache_put(key, data)
            return Entity(
                type=entity.type, value=entity.value, original=entity.original,
                confidence=entity.confidence, derived_from=entity.derived_from,
                metadata={**entity.metadata, **{k: v for k, v in data.items() if v}},
            )
        except Exception:
            logger.warning("WHOISEnricher: failed for %s", entity.value)
            return entity
