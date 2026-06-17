"""Base ABC for all POE entity extractors."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import Entity

__all__ = ["BaseExtractor"]


class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, text: str) -> list[Entity]:
        """Extract entities from normalized text (sync)."""

    async def async_extract(self, text: str) -> list[Entity]:
        """Async extraction — override in LLM-backed extractors. Default: no-op."""
        return []
