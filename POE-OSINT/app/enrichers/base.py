"""Base ABC for all POE entity enrichers."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import Entity

__all__ = ["BaseEnricher"]


class BaseEnricher(ABC):
    @abstractmethod
    async def enrich(self, entity: Entity) -> Entity:
        """Return enriched entity. Never raises — returns original on failure."""

    @abstractmethod
    def can_enrich(self, entity: Entity) -> bool:
        """Return True if this enricher applies to this entity."""
