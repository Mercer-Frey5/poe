"""
test_extractors.py — test unit sul RegexExtractor (v0.2).
"""

from __future__ import annotations

from app.models import Entity


def _values_of_type(entities: list[Entity], t: str) -> set[str]:
    return {e.value for e in entities if e.type == t}


# ─────────────────────────────────────────────────────────────
# Email
# ─────────────────────────────────────────────────────────────

class TestEmail:
    def test_basic(self, regex_extractor):
        e = regex_extractor.extract("Contatti: user@example.com")
        assert "user@example.com" in _values_of_type(e, "email")

    def test_multiple(self, regex_extractor):
        e = regex_extractor.extract("a@b.com e poi c.d@example.org")
        assert _values_of_type(e, "email") == {"a@b.com", "c.d@example.org"}

    def test_plus_addressing(self, regex_extractor):
        e = regex_extractor.extract("user+tag@example.com")
        assert "user+tag@example.com" in _values_of_type(e, "email")


# ─────────────────────────────────────────────────────────────
# IPv4
# ─────────────────────────────────────────────────────────────

class TestIpv4:
    def test_valid(self, regex_extractor):
        e = regex_extractor.extract("Log: 185.220.101.42")
        assert "185.220.101.42" in _values_of_type(e, "ipv4")

    def test_invalid_octet(self, regex_extractor):
        e = regex_extractor.extract("IP fasullo: 999.999.999.999")
        assert _values_of_type(e, "ipv4") == set()

    def test_private_and_public(self, regex_extractor):
        e = regex_extractor.extract("Gateway 192.168.1.1 e remote 8.8.8.8")
        assert _values_of_type(e, "ipv4") == {"192.168.1.1", "8.8.8.8"}


# ─────────────────────────────────────────────────────────────
# URL
# ─────────────────────────────────────────────────────────────

class TestUrl:
    def test_http_and_https(self, regex_extractor):
        e = regex_extractor.extract("http://a.com e https://b.org")
        assert _values_of_type(e, "url") == {"http://a.com", "https://b.org"}

    def test_trailing_punctuation_stripped(self, regex_extractor):
        e = regex_extractor.extract("Visita https://example.com.")
        assert "https://example.com" in _values_of_type(e, "url")

    def test_with_path_and_query(self, regex_extractor):
        e = regex_extractor.extract("https://login.example.com/verify?token=abc")
        assert "https://login.example.com/verify?token=abc" in _values_of_type(e, "url")


# ─────────────────────────────────────────────────────────────
# Domain
# ─────────────────────────────────────────────────────────────

class TestDomain:
    def test_common_tld(self, regex_extractor):
        e = regex_extractor.extract("Dominio: example.com")
        assert "example.com" in _values_of_type(e, "domain")

    def test_new_gtld(self, regex_extractor):
        e = regex_extractor.extract("Dominio: clouddrive-sync.xyz")
        assert "clouddrive-sync.xyz" in _values_of_type(e, "domain")

    def test_person_name_not_domain(self, regex_extractor):
        e = regex_extractor.extract("Email di Mario Rossi: mario.rossi@test.it")
        assert "mario.rossi" not in _values_of_type(e, "domain")

    def test_lowercase_normalization(self, regex_extractor):
        e = regex_extractor.extract("Dominio: Example.COM")
        assert "example.com" in _values_of_type(e, "domain")


# ─────────────────────────────────────────────────────────────
# Hash MD5 (v0.1)
# ─────────────────────────────────────────────────────────────

class TestHashMd5:
    def test_extracts_md5(self, regex_extractor):
        e = regex_extractor.extract("Hash: 44d88612fea8a8f36de82e1278abb02f")
        assert "44d88612fea8a8f36de82e1278abb02f" in _values_of_type(e, "hash_md5")

    def test_uppercase_normalized(self, regex_extractor):
        e = regex_extractor.extract("Hash: 44D88612FEA8A8F36DE82E1278ABB02F")
        assert "44d88612fea8a8f36de82e1278abb02f" in _values_of_type(e, "hash_md5")

    def test_too_short_not_extracted(self, regex_extractor):
        e = regex_extractor.extract("Fragment: abc123")
        assert _values_of_type(e, "hash_md5") == set()


# ─────────────────────────────────────────────────────────────
# Hash SHA-256 (v0.2 — nuovo)
# ─────────────────────────────────────────────────────────────

class TestHashSha256:
    SAMPLE = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_extracts_sha256(self, regex_extractor):
        e = regex_extractor.extract(f"Hash: {self.SAMPLE}")
        assert self.SAMPLE in _values_of_type(e, "hash_sha256")

    def test_uppercase_normalized(self, regex_extractor):
        e = regex_extractor.extract(f"Hash: {self.SAMPLE.upper()}")
        assert self.SAMPLE in _values_of_type(e, "hash_sha256")

    def test_sha256_does_not_double_extract_as_md5(self, regex_extractor):
        """Uno SHA-256 non deve apparire anche come hash_md5
        (i \\b nel pattern md5 prevengono il match parziale)."""
        e = regex_extractor.extract(f"Hash: {self.SAMPLE}")
        assert _values_of_type(e, "hash_md5") == set()


# ─────────────────────────────────────────────────────────────
# CVE (v0.2 — nuovo)
# ─────────────────────────────────────────────────────────────

class TestCve:
    def test_basic(self, regex_extractor):
        e = regex_extractor.extract("Patchata CVE-2024-12345 ieri.")
        assert "CVE-2024-12345" in _values_of_type(e, "cve")

    def test_lowercase_normalized(self, regex_extractor):
        e = regex_extractor.extract("Vedere cve-2017-0144 per dettagli.")
        assert "CVE-2017-0144" in _values_of_type(e, "cve")

    def test_long_id(self, regex_extractor):
        # Le CVE moderne possono avere id lunghi (fino a 7 cifre)
        e = regex_extractor.extract("CVE-2023-1234567 era un esempio.")
        assert "CVE-2023-1234567" in _values_of_type(e, "cve")

    def test_too_short_not_extracted(self, regex_extractor):
        e = regex_extractor.extract("CVE-2024-1")
        assert _values_of_type(e, "cve") == set()


# ─────────────────────────────────────────────────────────────
# Username
# ─────────────────────────────────────────────────────────────

class TestUsername:
    def test_basic(self, regex_extractor):
        # Dedup: @handle è estratto come social_handle, non username
        e = regex_extractor.extract("Contatta @johnsmith su Twitter")
        assert "@johnsmith" in _values_of_type(e, "social_handle")
        assert "@johnsmith" not in _values_of_type(e, "username")

    def test_email_at_not_username(self, regex_extractor):
        e = regex_extractor.extract("user@example.com")
        assert _values_of_type(e, "username") == set()

    def test_min_length(self, regex_extractor):
        e = regex_extractor.extract("Tag @ab in un tweet")
        assert "@ab" not in _values_of_type(e, "username")


# ─────────────────────────────────────────────────────────────
# Phone
# ─────────────────────────────────────────────────────────────

class TestPhone:
    def test_italian_mobile(self, regex_extractor):
        """v0.3: numero locale italiano viene normalizzato in E.164 con +39."""
        e = regex_extractor.extract("Cell: 347 1234567")
        assert "+393471234567" in _values_of_type(e, "phone")

    def test_international_plus(self, regex_extractor):
        """Numero con prefisso esplicito: rispetta il prefisso, normalizza."""
        e = regex_extractor.extract("Chiamare +39 347 1234567")
        assert "+393471234567" in _values_of_type(e, "phone")

    def test_foreign_number_respected(self, regex_extractor):
        """v0.3: numero estero (+44) NON viene forzato a IT."""
        e = regex_extractor.extract("UK office: +44 20 7946 0958")
        assert "+442079460958" in _values_of_type(e, "phone")

    def test_invalid_number_discarded(self, regex_extractor):
        """v0.3: numeri sintatticamente parsabili ma invalidi sono scartati."""
        e = regex_extractor.extract("Codice cliente: 12345")
        assert _values_of_type(e, "phone") == set()

    def test_original_preserved_on_extraction(self, regex_extractor):
        """v0.3: la forma originale del testo è preservata in `original`."""
        entities = regex_extractor.extract("Cell: 347 1234567")
        phones = [x for x in entities if x.type == "phone"]
        assert len(phones) == 1
        assert phones[0].value == "+393471234567"
        assert phones[0].original == "347 1234567"
