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

_API = "http://ip-api.com/json/{ip}?fields=status,country,city,isp,org,lat,lon"


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
