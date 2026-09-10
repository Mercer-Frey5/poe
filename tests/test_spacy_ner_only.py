"""Task 2: spaCy caricato NER-only resta funzionale e non carica pipe inutili."""
import pytest

spacy = pytest.importorskip("spacy")
from app.extractors.spacy_extractor import SpacyExtractor, _EXCLUDED_PIPES


@pytest.fixture(scope="module")
def extractor():
    try:
        return SpacyExtractor()
    except RuntimeError as e:
        pytest.skip(str(e))


def test_excludes_parser_and_tagger(extractor):
    for nlp in extractor._models:
        for pipe in _EXCLUDED_PIPES:
            assert pipe not in nlp.pipe_names


def test_still_extracts_person(extractor):
    ents = extractor.extract("Mario Rossi ha chiamato ieri.")
    assert any(e.type == "person_name" for e in ents)
