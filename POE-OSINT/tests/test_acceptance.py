"""
test_acceptance.py — runner pytest dei casi di accettazione YAML.

Scopre dinamicamente tutti i TC-*.yaml nella directory acceptance/,
li esegue contro il Recognizer completo (con SpacyExtractor reale se
disponibile, altrimenti stub che ritorna liste vuote → le asserzioni
su person_name vengono saltate automaticamente).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.extractors.regex_extractor import RegexExtractor
from app.models import Entity
from app.recognizer import Recognizer
from tests.acceptance.runner import AcceptanceCase, check_case


ACCEPTANCE_DIR = Path(__file__).parent / "acceptance"


def _collect_yaml_cases() -> list[Path]:
    return sorted(ACCEPTANCE_DIR.glob("TC-*.yaml"))


class _NoopSpacy:
    """Stub quando i modelli spaCy non sono installati."""

    def extract(self, text: str) -> list[Entity]:
        return []


@pytest.fixture(scope="module")
def recognizer():
    """
    Istanzia il Recognizer con SpacyExtractor vero se i modelli sono
    installati, altrimenti usa lo stub. Questo permette di far girare
    i test anche in ambienti CI senza modelli pesanti.
    """
    try:
        from app.extractors.spacy_extractor import SpacyExtractor
        spacy_ext = SpacyExtractor()
    except (RuntimeError, ImportError):
        spacy_ext = _NoopSpacy()

    return Recognizer(RegexExtractor(), spacy_ext)


@pytest.mark.parametrize(
    "yaml_path",
    _collect_yaml_cases(),
    ids=lambda p: p.stem,
)
def test_acceptance_case(yaml_path: Path, recognizer):
    case = AcceptanceCase.from_yaml(yaml_path)
    extracted = recognizer.recognize(case.input_text)
    violations = check_case(case, extracted)

    assert not violations, (
        f"\n--- Caso {case.id}: {case.title} ---\n"
        f"Violazioni:\n  " + "\n  ".join(violations)
        + "\n\nEntità effettivamente estratte:\n  "
        + "\n  ".join(f"[{e.type}] {e.value}" for e in extracted)
    )
