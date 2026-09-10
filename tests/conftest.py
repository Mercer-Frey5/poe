"""
conftest.py — configurazione comune dei test di POE v0.2.
"""

from __future__ import annotations

from typing import Iterable

import pytest

from app.extractors.regex_extractor import RegexExtractor
from app.models import Entity


@pytest.fixture(autouse=True)
def _clear_api_keys(monkeypatch):
    """Autouse: i test non devono mai dipendere dalle API key reali
    eventualmente presenti in .env sulla macchina di sviluppo (load_dotenv()
    le legge all'avvio dell'app). Un test che vuole esercitare il path "con
    key" la imposta esplicitamente con monkeypatch.setenv nel proprio corpo.

    L'elenco viene dal registro dell'app, non da una lista scritta a mano qui:
    quella copriva tre servizi su nove ed era rimasta indietro, cosi' la suite
    passava o falliva a seconda di quali chiavi lo sviluppatore avesse
    configurato. Aggiungere un servizio ora aggiorna l'isolamento da solo."""
    from app.main import _MANAGED_API_KEYS
    for var in _MANAGED_API_KEYS:
        monkeypatch.delenv(var, raising=False)


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
