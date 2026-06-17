"""WHOIS enricher — python-whois library."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

import whois

from app.enrichers.base import BaseEnricher
from app.models import Entity

logger = logging.getLogger(__name__)

__all__ = ["WHOISEnricher"]


def _fmt(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, list):
        d = d[0]
    if isinstance(d, (datetime, date)):
        return d.strftime("%Y-%m-%d")
    return str(d)


class WHOISEnricher(BaseEnricher):
    def can_enrich(self, entity: Entity) -> bool:
        return entity.type in ("domain", "url")

    async def enrich(self, entity: Entity) -> Entity:
        domain = entity.value
        if entity.type == "url":
            from urllib.parse import urlparse
            domain = urlparse(entity.value).hostname or entity.value
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(whois.whois, domain), timeout=10.0
            )
            ns = result.name_servers
            return Entity(
                type=entity.type, value=entity.value, original=entity.original,
                confidence=entity.confidence, derived_from=entity.derived_from,
                metadata={
                    **entity.metadata,
                    "registrar": result.registrar,
                    "creation_date": _fmt(result.creation_date),
                    "expiration_date": _fmt(result.expiration_date),
                    "registrant_org": result.org,
                    "name_servers": list(ns)[:3] if ns else [],
                },
            )
        except Exception:
            logger.warning("WHOISEnricher: failed for %s", domain)
            return entity
