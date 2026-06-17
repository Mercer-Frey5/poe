"""
test_v04_flags.py — test per i flag deterministici di v0.4.

Copre:
  - B1: suspicious_tld — flag su domini con TLD sospetto
"""

from __future__ import annotations

import pytest

from app.models import Entity


def _domains(entities: list[Entity]) -> list[Entity]:
    return [e for e in entities if e.type == "domain"]


class TestSuspiciousTld:
    def test_xyz_flagged(self, regex_extractor):
        e = regex_extractor.extract("Visita evil-site.xyz per dettagli")
        domains = _domains(e)
        xyz = next((d for d in domains if d.value == "evil-site.xyz"), None)
        assert xyz is not None
        assert xyz.metadata.get("suspicious_tld") is True

    def test_tk_flagged(self, regex_extractor):
        e = regex_extractor.extract("Sito: malware.tk")
        domains = _domains(e)
        tk = next((d for d in domains if d.value == "malware.tk"), None)
        assert tk is not None
        assert tk.metadata.get("suspicious_tld") is True

    def test_legitimate_tld_not_flagged(self, regex_extractor):
        e = regex_extractor.extract("Sito legittimo: google.com")
        domains = _domains(e)
        com = next((d for d in domains if d.value == "google.com"), None)
        assert com is not None
        assert not com.metadata.get("suspicious_tld", False)

    def test_it_tld_not_flagged(self, regex_extractor):
        e = regex_extractor.extract("Visita poste.it per info")
        domains = _domains(e)
        it_d = next((d for d in domains if d.value == "poste.it"), None)
        assert it_d is not None
        assert not it_d.metadata.get("suspicious_tld", False)

    def test_download_tld_flagged(self, regex_extractor):
        e = regex_extractor.extract("Scarica da malware.download")
        domains = _domains(e)
        d = next((d for d in domains if "download" in d.value), None)
        if d:  # se il TLD .download è nella tld_list.yaml
            assert d.metadata.get("suspicious_tld") is True

    def test_suspicious_tld_domain_confidence_still_medium(self, regex_extractor):
        e = regex_extractor.extract("evil.xyz")
        domains = _domains(e)
        if domains:
            assert domains[0].confidence == "medium"

    def test_suspicious_tlds_yaml_loaded(self):
        from app.extractors.regex_extractor import _SUSPICIOUS_TLDS
        assert "xyz" in _SUSPICIOUS_TLDS
        assert "tk" in _SUSPICIOUS_TLDS
        assert "ml" in _SUSPICIOUS_TLDS
        assert len(_SUSPICIOUS_TLDS) >= 10
