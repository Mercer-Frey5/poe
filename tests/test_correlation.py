"""Correlazione: URL→dominio (host) ed email→dominio (parte dominio), marcati derivati."""
from app.recognizer import Recognizer
from app.extractors.regex_extractor import RegexExtractor


class _NoopSpacy:
    def extract(self, text):
        return []


def _rec():
    return Recognizer(RegexExtractor(), _NoopSpacy())


def test_url_yields_correlated_domain():
    ents = _rec().recognize("apri http://secure-update.xyz/verify")
    doms = {e.value: e for e in ents if e.type == "domain"}
    assert "secure-update.xyz" in doms
    assert doms["secure-update.xyz"].metadata.get("derived_source") == "url"
    assert doms["secure-update.xyz"].derived_from == "http://secure-update.xyz/verify"


def test_email_yields_correlated_domain():
    ents = _rec().recognize("scrivi a admin@malware.com")
    doms = {e.value: e for e in ents if e.type == "domain"}
    assert "malware.com" in doms
    assert doms["malware.com"].metadata.get("derived_source") == "email"


def test_literal_domain_not_marked_derived():
    ents = _rec().recognize("vai su example.com adesso")
    doms = {e.value: e for e in ents if e.type == "domain"}
    assert "example.com" in doms
    assert doms["example.com"].metadata.get("derived_source") is None
