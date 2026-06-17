"""
test_recognizer.py — test integrazione del Recognizer (v0.2).

Verifica integrazione completa:
- Pipeline regex + spaCy + dedup (invariato da v0.1)
- Deobfuscazione e ricostruzione del campo `original` (v0.2)
"""

from __future__ import annotations

from app.extractors.regex_extractor import RegexExtractor
from app.models import Entity
from app.recognizer import Recognizer


def _values_of(entities: list[Entity], t: str) -> set[str]:
    return {e.value for e in entities if e.type == t}


def _entity_for(entities: list[Entity], type_: str, value: str) -> Entity | None:
    """Helper: trova la singola Entity con (type, value) o None."""
    for e in entities:
        if e.type == type_ and e.value == value:
            return e
    return None


class TestDedup:
    def test_url_absorbs_domain(self, regex_extractor, fake_spacy):
        rec = Recognizer(regex_extractor, fake_spacy([]))
        entities = rec.recognize("Link: https://evil.com/payload e anche evil.com")
        assert "https://evil.com/payload" in _values_of(entities, "url")
        assert "evil.com" not in _values_of(entities, "domain")

    def test_email_absorbs_domain(self, regex_extractor, fake_spacy):
        rec = Recognizer(regex_extractor, fake_spacy([]))
        entities = rec.recognize("Email: user@foo.com e il dominio foo.com")
        assert "user@foo.com" in _values_of(entities, "email")
        assert "foo.com" not in _values_of(entities, "domain")

    def test_domain_standalone_survives(self, regex_extractor, fake_spacy):
        rec = Recognizer(regex_extractor, fake_spacy([]))
        entities = rec.recognize("Solo dominio: clouddrive-sync.xyz")
        assert "clouddrive-sync.xyz" in _values_of(entities, "domain")


class TestIntegration:
    def test_full_pipeline(self, regex_extractor, fake_spacy):
        text = (
            "Oggetto: segnalazione sospetta di Mario Rossi.\n"
            "Mittente: support@paypa1.com (IP 185.220.101.42).\n"
            "Link ricevuto: https://login-paypa1.com/verify\n"
            "Hash allegato: 44d88612fea8a8f36de82e1278abb02f\n"
            "SHA-256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n"
            "Vulnerabilità: CVE-2024-12345\n"
            "Telefono di contatto: +39 347 1234567\n"
            "Account social: @mrossi_official"
        )
        spacy = fake_spacy([Entity("person_name", "Mario Rossi")])
        rec = Recognizer(regex_extractor, spacy)
        entities = rec.recognize(text)

        assert "support@paypa1.com" in _values_of(entities, "email")
        assert "185.220.101.42" in _values_of(entities, "ipv4")
        assert "https://login-paypa1.com/verify" in _values_of(entities, "url")
        assert "44d88612fea8a8f36de82e1278abb02f" in _values_of(entities, "hash_md5")
        assert ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                in _values_of(entities, "hash_sha256"))
        assert "CVE-2024-12345" in _values_of(entities, "cve")
        assert "+393471234567" in _values_of(entities, "phone")
        assert "@mrossi_official" in _values_of(entities, "social_handle")
        assert "Mario Rossi" in _values_of(entities, "person_name")

        assert "paypa1.com" not in _values_of(entities, "domain")
        assert "login-paypa1.com" not in _values_of(entities, "domain")

    def test_empty_input(self, regex_extractor, fake_spacy):
        rec = Recognizer(regex_extractor, fake_spacy([]))
        assert rec.recognize("") == []

    def test_no_entities_in_prose(self, regex_extractor, fake_spacy):
        rec = Recognizer(regex_extractor, fake_spacy([]))
        result = rec.recognize("Questa è una frase senza alcuna entità OSINT.")
        assert result == []

    def test_output_is_sorted(self, regex_extractor, fake_spacy):
        rec = Recognizer(regex_extractor, fake_spacy([]))
        entities = rec.recognize(
            "b@x.com, a@x.com, https://z.com, https://a.com"
        )
        keys = [(e.type, e.value.lower()) for e in entities]
        assert keys == sorted(keys)


# ─────────────────────────────────────────────────────────────
# Deobfuscazione: comportamento end-to-end
# ─────────────────────────────────────────────────────────────

class TestDeobfuscation:
    def test_url_hxxp_deobfuscated(self, regex_extractor, fake_spacy):
        rec = Recognizer(regex_extractor, fake_spacy([]))
        entities = rec.recognize("Sito: hxxp://malicious.com/path")
        url = _entity_for(entities, "url", "http://malicious.com/path")
        assert url is not None
        assert url.original == "hxxp://malicious.com/path"
        assert url.is_deobfuscated

    def test_url_hxxps_with_brackets(self, regex_extractor, fake_spacy):
        rec = Recognizer(regex_extractor, fake_spacy([]))
        entities = rec.recognize("URL: hxxps://login-paypa1[.]com/verify")
        url = _entity_for(entities, "url", "https://login-paypa1.com/verify")
        assert url is not None
        assert url.original == "hxxps://login-paypa1[.]com/verify"

    def test_email_at_dot_deobfuscated(self, regex_extractor, fake_spacy):
        rec = Recognizer(regex_extractor, fake_spacy([]))
        entities = rec.recognize("Mittente: mario(at)evil(dot)com")
        em = _entity_for(entities, "email", "mario@evil.com")
        assert em is not None
        assert em.original == "mario(at)evil(dot)com"

    def test_domain_with_brackets(self, regex_extractor, fake_spacy):
        rec = Recognizer(regex_extractor, fake_spacy([]))
        entities = rec.recognize("Dominio: malicious[.]xyz")
        d = _entity_for(entities, "domain", "malicious.xyz")
        assert d is not None
        assert d.original == "malicious[.]xyz"

    def test_normal_text_no_original_set(self, regex_extractor, fake_spacy):
        """Su testo non defanged, original deve coincidere con value."""
        rec = Recognizer(regex_extractor, fake_spacy([]))
        entities = rec.recognize("URL normale: https://example.com/x")
        url = _entity_for(entities, "url", "https://example.com/x")
        assert url is not None
        assert url.original == url.value
        assert not url.is_deobfuscated

    def test_mixed_defanged_and_normal(self, regex_extractor, fake_spacy):
        """Testo con entità defanged e non — devono coesistere correttamente."""
        rec = Recognizer(regex_extractor, fake_spacy([]))
        entities = rec.recognize(
            "Defanged: hxxps://evil[.]com/x\n"
            "Pulito:   https://normal.org/y"
        )
        evil = _entity_for(entities, "url", "https://evil.com/x")
        normal = _entity_for(entities, "url", "https://normal.org/y")
        assert evil is not None and evil.is_deobfuscated
        assert normal is not None and not normal.is_deobfuscated
