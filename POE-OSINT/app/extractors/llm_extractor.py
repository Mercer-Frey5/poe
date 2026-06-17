"""LLM-backed extractor for org_name and address entity types."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from app.extractors.base import BaseExtractor
from app.llm.base import LLMBackend
from app.models import Entity

logger = logging.getLogger(__name__)

__all__ = ["LLMExtractor"]

_PROMPTS_DIR = Path(__file__).parent.parent / "llm" / "prompts"


def _load_prompt(name: str) -> dict:
    with open(_PROMPTS_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


class LLMExtractor(BaseExtractor):
    """Extracts org_name and address entities using an LLM backend."""

    def __init__(self, backend: LLMBackend) -> None:
        self._backend = backend
        self._prompt = _load_prompt("extraction")

    def extract(self, text: str) -> list[Entity]:
        return []  # sync no-op — use async_extract

    async def async_extract(self, text: str) -> list[Entity]:
        if not await self._backend.is_available():
            return []

        prompt = self._prompt["user"].replace("{text}", text[:2000])
        system = self._prompt["system"]

        try:
            raw = await self._backend.generate(prompt, system)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:])
            if raw.endswith("```"):
                raw = "\n".join(raw.split("\n")[:-1])
            data = json.loads(raw)
        except Exception:
            logger.warning("LLMExtractor: failed to parse JSON response")
            return []

        entities: list[Entity] = []

        for org in data.get("org_names", []):
            org = str(org).strip()
            if not org:
                continue
            entities.append(Entity(
                type="org_name",
                value=org,
                confidence="low",
                metadata={"extractor": "llm", "type_hint": "unknown"},
            ))

        for addr in data.get("addresses", []):
            full = str(addr.get("full_address", "")).strip()
            if not full:
                continue
            entities.append(Entity(
                type="address",
                value=full.lower(),
                confidence="low",
                metadata={
                    "extractor": "llm",
                    "full_address": full,
                    "city": addr.get("city", ""),
                    "country": addr.get("country", ""),
                },
            ))

        return entities
