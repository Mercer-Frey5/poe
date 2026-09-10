"""Verifica che app/config/wmn-data.json (dataset WhatsMyName vendorizzato)
abbia lo schema atteso da whatsmyname_lookup in live_lookup.py."""
import json
from pathlib import Path

_WMN_PATH = Path(__file__).resolve().parent.parent / "app" / "config" / "wmn-data.json"


def test_wmn_dataset_file_exists():
    assert _WMN_PATH.exists()


def test_wmn_dataset_has_expected_shape():
    data = json.loads(_WMN_PATH.read_text(encoding="utf-8"))
    assert "sites" in data
    assert isinstance(data["sites"], list)
    assert len(data["sites"]) > 100  # dataset reale ha centinaia di siti


def test_wmn_dataset_sites_have_required_fields():
    data = json.loads(_WMN_PATH.read_text(encoding="utf-8"))
    for site in data["sites"]:
        assert "name" in site
        assert "uri_check" in site
        assert "e_code" in site
        assert "e_string" in site


def test_wmn_dataset_most_sites_support_simple_get_substitution():
    # ~97% dei siti usano GET + {account} nell'URL (il checker minimo li
    # copre); una minoranza (~21/719) usa POST con post_body/headers dedicati
    # (uri_check punta a un endpoint fisso) — non ancora supportati dal
    # checker, che li salta esplicitamente (vedi whatsmyname_lookup).
    data = json.loads(_WMN_PATH.read_text(encoding="utf-8"))
    sites = data["sites"]
    get_substitutable = [s for s in sites if "{account}" in s.get("uri_check", "")]
    assert len(get_substitutable) > 600
