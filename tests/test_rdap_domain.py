"""Task 4: parsing RDAP dominio."""
from app.enrichers.whois_enricher import _rdap_domain_parse


def _sample():
    return {
        "events": [
            {"eventAction": "registration", "eventDate": "1997-09-15T04:00:00Z"},
            {"eventAction": "expiration", "eventDate": "2028-09-14T04:00:00Z"},
            {"eventAction": "last changed", "eventDate": "2019-09-09T15:39:04Z"},
        ],
        "status": ["client delete prohibited", "server update prohibited"],
        "secureDNS": {"delegationSigned": False},
        "nameservers": [{"ldhName": "NS1.GOOGLE.COM"}, {"ldhName": "NS2.GOOGLE.COM"}],
        "entities": [
            {"roles": ["registrar"],
             "vcardArray": ["vcard", [["version", {}, "text", "4.0"],
                                       ["fn", {}, "text", "MarkMonitor Inc."]]]},
        ],
    }


def test_registrar_extracted():
    assert _rdap_domain_parse(_sample())["registrar"] == "MarkMonitor Inc."


def test_dates_extracted():
    out = _rdap_domain_parse(_sample())
    assert out["creation_date"] == "1997-09-15"
    assert out["expiration_date"] == "2028-09-14"
    assert out["updated_date"] == "2019-09-09"


def test_status_and_dnssec():
    out = _rdap_domain_parse(_sample())
    assert "client delete prohibited" in out["status"]
    assert out["dnssec"] == "unsigned"


def test_nameservers_lowercased_capped():
    out = _rdap_domain_parse(_sample())
    assert out["name_servers"][0] == "ns1.google.com"
    assert len(out["name_servers"]) <= 4
