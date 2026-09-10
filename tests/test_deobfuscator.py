"""
test_deobfuscator.py — test unit sul preprocessore di deobfuscazione.
"""

from __future__ import annotations

from app.deobfuscator import deobfuscate


class TestSubstitutions:
    def test_hxxp(self):
        r = deobfuscate("hxxp://example.com")
        assert r.normalized == "http://example.com"

    def test_hxxps_priority_over_hxxp(self):
        """hxxps:// non deve essere scomposto in hxxp + s://"""
        r = deobfuscate("hxxps://example.com")
        assert r.normalized == "https://example.com"

    def test_brackets_dot(self):
        r = deobfuscate("evil[.]com")
        assert r.normalized == "evil.com"

    def test_brackets_colon(self):
        r = deobfuscate("host[:]8080")
        assert r.normalized == "host:8080"

    def test_at_text(self):
        r = deobfuscate("user(at)example.com")
        assert r.normalized == "user@example.com"

    def test_dot_text(self):
        r = deobfuscate("user(at)example(dot)com")
        assert r.normalized == "user@example.com"

    def test_combined(self):
        r = deobfuscate("Visita hxxps://login-bank[.]com/verify")
        assert r.normalized == "Visita https://login-bank.com/verify"

    def test_no_substitution_passes_through(self):
        r = deobfuscate("https://normal.com")
        assert r.normalized == "https://normal.com"

    def test_empty_string(self):
        r = deobfuscate("")
        assert r.normalized == ""


class TestIndexMap:
    def test_substring_recovery_simple(self):
        r = deobfuscate("evil[.]com")
        # Nel normalized "evil.com" il dominio sta a 0..8
        assert r.original_substring(0, 8) == "evil[.]com"

    def test_substring_recovery_url(self):
        r = deobfuscate("hxxps://login[.]example[.]com")
        # normalized: "https://login.example.com" (lunghezza 25)
        assert r.normalized == "https://login.example.com"
        # L'URL completo nel normalized è 0..25, deve mappare all'intero originale
        assert r.original_substring(0, 25) == "hxxps://login[.]example[.]com"

    def test_substring_recovery_partial(self):
        """Recupero parziale di una zona non deobfuscata."""
        r = deobfuscate("Pre hxxp://x.com Post")
        # "Pre " sta sia nell'originale sia nel normalized
        assert r.original_substring(0, 4) == "Pre "

    def test_no_deobfuscation_identity(self):
        r = deobfuscate("plain text")
        assert r.original_substring(0, 10) == "plain text"
