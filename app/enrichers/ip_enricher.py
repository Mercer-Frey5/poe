"""IP geolocation enricher — ip-api.com (free, no key, 45 req/min).

NOTE: ip-api.com free plan uses HTTP only. SSRF risk mitigated by
enforcing is_global check in can_enrich before any outbound call.
"""
from __future__ import annotations

import ipaddress
import logging

import httpx

from app.enrichers.base import BaseEnricher
from app.models import Entity

logger = logging.getLogger(__name__)

__all__ = ["IPEnricher"]

_API = "http://ip-api.com/json/{ip}?fields=status,country,countryCode,city,isp,org,lat,lon"


class IPEnricher(BaseEnricher):
    def can_enrich(self, entity: Entity) -> bool:
        if entity.type != "ipv4" or entity.metadata.get("bogon"):
            return False
        try:
            return ipaddress.ip_address(entity.value).is_global
        except ValueError:
            return False

    async def enrich(self, entity: Entity) -> Entity:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(_API.format(ip=entity.value))
                data = resp.json()
            if data.get("status") != "success":
                return entity
            return Entity(
                type=entity.type, value=entity.value, original=entity.original,
                confidence=entity.confidence, derived_from=entity.derived_from,
                metadata={
                    **entity.metadata,
                    "country": data.get("country"),
                    "country_code": data.get("countryCode"),
                    "city": data.get("city"),
                    "isp": data.get("isp"),
                    "org": data.get("org"),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                },
            )
        except Exception:
            logger.warning("IPEnricher: failed for %s", entity.value)
            return entity

    _BATCH_API = "http://ip-api.com/batch?fields=status,message,query,country,countryCode,city,isp,org,lat,lon"

    @staticmethod
    def _parse_batch(data: list[dict]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for row in data or []:
            if row.get("status") != "success":
                continue
            q = row.get("query")
            if not q:
                continue
            out[q] = {
                "country": row.get("country"), "country_code": row.get("countryCode"),
                "city": row.get("city"), "isp": row.get("isp"), "org": row.get("org"),
                "lat": row.get("lat"), "lon": row.get("lon"),
            }
        return out

    async def _post_batch(self, ips: list[str]) -> dict[str, dict]:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(self._BATCH_API, json=ips)
            resp.raise_for_status()
            return self._parse_batch(resp.json())

    async def enrich_batch(self, ips: list[str]) -> dict[str, dict]:
        """Geolocalizza in blocco. Filtra IP globali (no privati/bogon). {} su errore."""
        globals_ = []
        for ip in ips:
            try:
                if ipaddress.ip_address(ip).is_global:
                    globals_.append(ip)
            except ValueError:
                continue
        if not globals_:
            return {}
        try:
            return await self._post_batch(globals_)
        except Exception:
            logger.warning("IPEnricher.enrich_batch failed for %d ips", len(globals_))
            return {}
