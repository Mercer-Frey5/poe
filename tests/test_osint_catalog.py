"""Task 1: catalogo OSINT — load_catalog, resources_for_type, resource_url."""
import pytest
from app import osint_catalog


def test_load_catalog_covers_threat_intel_types():
    catalog = osint_catalog.load_catalog()
    by_type: dict[str, int] = {}
    for r in catalog:
        for t in r["applies_to"]["entity_types"]:
            by_type[t] = by_type.get(t, 0) + 1
    for t in ("ipv4", "domain", "url", "hash_md5", "hash_sha256", "cve"):
        assert by_type.get(t, 0) >= 1, f"nessuna risorsa per {t}"


def test_load_catalog_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(osint_catalog, "_CATALOG_YAML", tmp_path / "nope.yaml")
    with pytest.raises(RuntimeError):
        osint_catalog.load_catalog()


def test_load_catalog_missing_required_field_raises(tmp_path, monkeypatch):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "resources:\n"
        "  - id: x\n"
        "    kind: website\n"
        "    applies_to:\n"
        "      entity_types: [ipv4]\n"
        "    validation_status: unverified\n",  # manca 'name'
        encoding="utf-8",
    )
    monkeypatch.setattr(osint_catalog, "_CATALOG_YAML", bad)
    with pytest.raises(RuntimeError):
        osint_catalog.load_catalog()


def test_resources_for_type_ipv4_only_relevant():
    res = osint_catalog.resources_for_type("ipv4")
    names = {r["name"] for r in res}
    assert "AbuseIPDB" in names
    assert "Shodan" in names
    assert all("ipv4" in r["applies_to"]["entity_types"] for r in res)


def test_resources_for_type_person_name_not_regressed():
    res = osint_catalog.resources_for_type("person_name")
    assert len(res) >= 15  # ~20 voci storiche, non toccate da questo task


def test_resources_for_type_unknown_type_empty():
    # Tipo non presente in nessuna voce del catalogo -> nessuna risorsa.
    # (tax_id non è più adatto: ora mappa a site-cf, decoder locale del CF.)
    assert osint_catalog.resources_for_type("__tipo_inesistente__") == []


def test_resource_url_with_template_encodes_value():
    resource = {"url_template": "https://www.abuseipdb.com/check/{value}"}
    assert osint_catalog.resource_url(resource, "8.8.8.8") == "https://www.abuseipdb.com/check/8.8.8.8"


def test_resource_url_encodes_special_chars():
    resource = {"url_template": "https://www.virustotal.com/gui/search/{value}"}
    url = osint_catalog.resource_url(resource, "http://a.b/c?d=e")
    assert "/" not in url.split("/search/")[1]  # value interamente urlencoded, niente slash residui


def test_resource_url_without_template_falls_back_to_url():
    resource = {"url": "https://www.google.com/"}
    assert osint_catalog.resource_url(resource, "qualcosa") == "https://www.google.com/"


def test_resource_url_malformed_template_returns_none():
    resource = {"url_template": "https://x.test/{missing_placeholder}"}
    assert osint_catalog.resource_url(resource, "8.8.8.8") is None
