"""
test_tld_list.py — verifica integrità del seed tld_list.yaml caricato in
_KNOWN_TLDS al modulo-load. Loader condiviso testato in test_config_loader.py.
"""

from __future__ import annotations

from app.extractors.regex_extractor import _KNOWN_TLDS


class TestKnownTlds:
    def test_loads_seed_yaml(self):
        assert isinstance(_KNOWN_TLDS, frozenset)
        assert len(_KNOWN_TLDS) > 0

    def test_essential_tlds_present(self):
        for essential in {"com", "org", "net", "it", "eu"}:
            assert essential in _KNOWN_TLDS, f"manca TLD essenziale: {essential}"

    def test_yaml_yes_no_keyword_handled(self):
        # 'no' è keyword YAML (= False) senza quoting. Il seed la quota.
        assert "no" in _KNOWN_TLDS
        assert False not in _KNOWN_TLDS

    def test_all_entries_lowercase(self):
        for tld in _KNOWN_TLDS:
            assert tld == tld.lower()
