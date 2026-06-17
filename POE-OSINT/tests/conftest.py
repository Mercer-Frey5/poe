"""
conftest.py — configurazione comune dei test di POE v0.2.
"""

from __future__ import annotations

from typing import Iterable

import pytest

from app.extractors.regex_extractor import RegexExtractor
from app.models import Entity


@pytest.fixture
def regex_extractor() -> RegexExtractor:
    return RegexExtractor()


class _FakeSpacy:
    """Stub di SpacyExtractor: ritorna entity solo se il value è nel testo."""

    def __init__(self, entities: Iterable[Entity] | None = None) -> None:
        self._entities = list(entities or [])

    def extract(self, text: str) -> list[Entity]:
        return [e for e in self._entities if e.value in text]


@pytest.fixture
def fake_spacy():
    return _FakeSpacy
