"""Enricher registry for on-demand entity enrichment."""
from __future__ import annotations

import asyncio
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
                # chain: ogni enricher arricchisce il risultato del precedente, cosi' piu'
                # enricher sullo stesso tipo (es. IP: geo + RDAP) si COMPONGONO invece di
                # sovrascriversi (prima passava 'entity' originale -> il 2o perdeva il 1o).
                if enricher.can_enrich(result[i]):
                    try:
                        result[i] = await enricher.enrich(result[i])
                    except Exception:
                        logger.warning("Enricher %s failed", enricher.__class__.__name__)
        return result

    async def enrich_all(self, entities, *, timeout: float = 4.0):
        """Arricchisce tutte le entità: geo IP in batch (1 call) + resto enricher
        concorrenti. Timeout difensivo. Non solleva mai (ritorna ciò che ha)."""
        result = list(entities)

        async def _run():
            # 1) Geo IP in blocco se un enricher espone enrich_batch
            batcher = next((e for e in self._enrichers if hasattr(e, "enrich_batch")), None)
            if batcher is not None:
                ips = [e.value for e in result
                       if e.type == "ipv4" and not e.metadata.get("bogon")]
                if ips:
                    geo = await batcher.enrich_batch(ips)
                    for i, e in enumerate(result):
                        meta = geo.get(e.value)
                        if meta:
                            merged = {**e.metadata, **{k: v for k, v in meta.items() if v}}
                            result[i] = Entity(
                                type=e.type, value=e.value, original=e.original,
                                confidence=e.confidence, derived_from=e.derived_from,
                                metadata=merged,
                            )

            # 2) Enricher per-entità concorrenti (RDAP IP, WHOIS dominio). Salta il batcher.
            async def _one(i, e):
                cur = e
                for enr in self._enrichers:
                    if enr is batcher:
                        continue
                    if enr.can_enrich(cur):
                        try:
                            cur = await enr.enrich(cur)
                        except Exception:
                            logger.warning("Enricher %s failed", enr.__class__.__name__)
                return i, cur

            done = await asyncio.gather(
                *[_one(i, e) for i, e in enumerate(result)], return_exceptions=True
            )
            for r in done:
                if isinstance(r, tuple):
                    result[r[0]] = r[1]

        try:
            await asyncio.wait_for(_run(), timeout=timeout)
        except Exception:
            logger.warning("enrich_all timeout/errore — ritorno parziale")
        return result
