import pytest
from app.extractors.regex_extractor import RegexExtractor

extractor = RegexExtractor()


def test_private_ip_flagged_as_bogon():
    entities = extractor.extract("Connessione da 192.168.1.1")
    ip = next((e for e in entities if e.type == "ipv4"), None)
    assert ip is not None
    assert ip.metadata.get("bogon") is True
    assert ip.metadata.get("bogon_type") == "private"
    assert ip.confidence == "low"


def test_loopback_ip_flagged_as_bogon():
    entities = extractor.extract("Host: 127.0.0.1")
    ip = next((e for e in entities if e.type == "ipv4"), None)
    assert ip is not None
    assert ip.metadata.get("bogon") is True
    assert ip.metadata.get("bogon_type") == "loopback"


def test_public_ip_not_bogon():
    entities = extractor.extract("Server IP: 8.8.8.8")
    ip = next((e for e in entities if e.type == "ipv4"), None)
    assert ip is not None
    assert not ip.metadata.get("bogon")
    assert ip.confidence == "medium"


def test_italian_street_address_extracted():
    entities = extractor.extract("Abita in Via Roma 42, 00100 Roma.")
    addresses = [e for e in entities if e.type == "address"]
    assert len(addresses) >= 1
    assert any("Via Roma" in e.metadata.get("full_address", "") for e in addresses)


def test_address_confidence_medium():
    entities = extractor.extract("Sede: Corso Vittorio Emanuele 100, 20100 Milano")
    addresses = [e for e in entities if e.type == "address"]
    assert addresses
    assert addresses[0].confidence == "medium"
    assert addresses[0].metadata.get("extractor") == "regex"


def test_plain_number_not_extracted_as_address():
    entities = extractor.extract("Prezzo: 42 euro, sconto 10")
    assert not any(e.type == "address" for e in entities)
