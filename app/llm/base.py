"""Base ABC for all POE LLM backends."""
from __future__ import annotations

from abc import ABC, abstractmethod

__all__ = ["LLMBackend"]


class LLMBackend(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return model identifier string."""

    @abstractmethod
    async def generate(self, prompt: str, system: str = "") -> str:
        """Generate a response. Raise on hard errors."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Return True if backend is reachable."""

    def unload(self) -> None:
        """Libera eventuali pesi dalla memoria/VRAM (handoff con l'hub vocale).
        Default no-op: i backend senza pesi locali (es. Ollama) non fanno nulla;
        MLX la sovrascrive per sfrattare il modello dalla VRAM Metal."""
        return None
