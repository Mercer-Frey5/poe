"""Enricher registry for on-demand entity enrichment."""
from __future__ import annotations

import logging

from app.enrichers.base import BaseEnricher
from app.models import Entity

logger = logging.getLogger(__name__)

__all__ = ["EnricherRegistry"]


class EnricherRegistry:
    def __init__(self, enrichers: list[BaseEnricher]) -> None:
        self._enrichers = enrichers

    async def enrich_on_demand(
        self,
        entity_type: str,
        entity_value: str,
        entities: list[Entity],
    ) -> list[Entity]:
        """Enrich entities matching type+value. Returns updated list."""
        result = list(entities)
        for i, entity in enumerate(result):
            if entity.type != entity_type or entity.value != entity_value:
                continue
            for enricher in self._enrichers:
                if enricher.can_enrich(entity):
                    try:
                        result[i] = await enricher.enrich(entity)
                    except Exception:
                        logger.warning("Enricher %s failed", enricher.__class__.__name__)
        return result
