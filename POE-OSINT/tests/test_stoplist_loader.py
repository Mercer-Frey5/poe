"""
test_stoplist_loader.py — verifica integrità della stoplist person_name
caricata in _PERSON_NAME_STOPLIST. Loader condiviso testato in
test_config_loader.py.
"""

from __future__ import annotations

from app.extractors.spacy_extractor import _PERSON_NAME_STOPLIST


class TestStoplistContent:
    def test_loaded_at_import(self):
        assert isinstance(_PERSON_NAME_STOPLIST, frozenset)
        assert len(_PERSON_NAME_STOPLIST) > 0

    def test_essential_entries_present(self):
        for entry in {"contatto", "mittente", "from", "subject", "hash"}:
            assert entry in _PERSON_NAME_STOPLIST, f"manca voce: {entry}"

    def test_all_entries_lowercase_stripped(self):
        for word in _PERSON_NAME_STOPLIST:
            assert word == word.lower(), f"non lowercase: {word!r}"
            assert word == word.strip(), f"non strippato: {word!r}"
