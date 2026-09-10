"""reputation_enricher.py — flagga IOC noti malevoli via lookup locale (no rete)."""
from __future__ import annotations

from app.enrichers.base import BaseEnricher
from app.models import Entity
from app.reputation import store

__all__ = ["ReputationEnricher"]


class ReputationEnricher(BaseEnricher):
    _TYPES = {"ipv4", "domain", "url", "hash_sha256", "hash_md5"}

    def can_enrich(self, entity: Entity) -> bool:
        return entity.type in self._TYPES

    async def enrich(self, entity: Entity) -> Entity:
        try:
            hits = store.lookup(entity.value)
        except Exception:
            return entity
        if not hits:
            return entity
        sources = sorted({h["source"] for h in hits})
        threat = next((h["threat"] for h in hits if h.get("threat")), None)
        reference = next((h["reference"] for h in hits if h.get("reference")), None)
        updated_at = max((h["updated_at"] for h in hits if h.get("updated_at")), default=None)
        # hits: dettaglio per singola fonte (l'espansione della entity-card lo
        # mostra riga per riga). I campi aggregati sopra restano per il badge
        # di rischio/tooltip, che non ha bisogno del dettaglio per-fonte.
        per_source_hits = [
            {
                "source": h["source"], "threat": h.get("threat"),
                "reference": h.get("reference"), "updated_at": h.get("updated_at"),
            }
            for h in hits
        ]
        return Entity(
            type=entity.type, value=entity.value, original=entity.original,
            confidence=entity.confidence, derived_from=entity.derived_from,
            metadata={**entity.metadata, "reputation": {
                "malicious": True, "sources": sources,
                "threat": threat, "reference": reference,
                "updated_at": updated_at, "hits": per_source_hits,
            }},
        )
