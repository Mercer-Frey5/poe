"""Ollama LLM backend for POE."""
from __future__ import annotations

import logging

import ollama

from app.llm.base import LLMBackend

logger = logging.getLogger(__name__)

__all__ = ["OllamaBackend"]


class OllamaBackend(LLMBackend):
    def __init__(
        self,
        model: str = "qwen2.5:9b",
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._timeout = timeout
        self._client = ollama.AsyncClient(host=base_url)

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, prompt: str, system: str = "") -> str:
        response = await self._client.generate(
            model=self._model,
            prompt=prompt,
            system=system,
            options={"temperature": 0.1},
        )
        return response.response

    async def is_available(self) -> bool:
        try:
            await self._client.list()
            return True
        except Exception:
            return False
