"""Task 2: parser dei feed abuse.ch (dati mock, no rete)."""
import pytest
from app.reputation import feeds


def test_parse_threatfox_json():
    raw = (
        '{"1": [{"ioc_value": "9.9.9.9:443", "ioc_type": "ip:port", '
        '"malware": "Cobalt Strike", "reference": "http://tf/1"}],'
        ' "2": [{"ioc_value": "Evil.COM", "ioc_type": "domain", "malware": "Emotet", "reference": null}],'
        ' "3": [{"ioc_value": "ABC123", "ioc_type": "sha256_hash", "malware": "X", "reference": "http://tf/3"}]}'
    )
    rows = {r["value"]: r for r in feeds.parse_threatfox_json(raw)}
    assert rows["9.9.9.9"]["type"] == "ipv4"          # porta rimossa
    assert rows["9.9.9.9"]["threat"] == "Cobalt Strike"
    assert rows["evil.com"]["type"] == "domain"        # lowercase
    assert rows["abc123"]["type"] == "hash_sha256"     # lowercase


def test_parse_threatfox_json_skips_malformed():
    raw = ('{"ok": "ok",'                                  # gruppo non-lista (envelope)
           ' "1": [{"ioc_value": 12345, "ioc_type": "domain", "malware": "X"}],'  # value non-str
           ' "2": [{"ioc_value": "good.com", "ioc_type": "domain", "malware": "Y"}]}')
    rows = feeds.parse_threatfox_json(raw)
    vals = [r["value"] for r in rows]
    assert vals == ["good.com"]           # solo la riga valida, nessun crash


def test_parse_urlhaus_csv():
    raw = (
        "# comment line\n"
        '"1","2024-01-01","http://bad.site/x","online","2024-01-02","malware_download","tag","http://uh/1","rep"\n'
    )
    rows = feeds.parse_urlhaus_csv(raw)
    assert rows[0]["value"] == "http://bad.site/x"
    assert rows[0]["type"] == "url"
    assert rows[0]["threat"] == "malware_download"
    assert rows[0]["reference"] == "http://uh/1"


def test_parse_feodo_json():
    raw = '[{"ip_address": "5.5.5.5", "port": 443, "malware": "Dridex"}]'
    rows = feeds.parse_feodo_json(raw)
    assert rows[0] == {"value": "5.5.5.5", "type": "ipv4",
                       "threat": "Dridex",
                       "reference": "https://feodotracker.abuse.ch/browse/"}


def test_parse_mb_txt():
    raw = "# header\nAABBCC\nDDEEFF\n"
    rows = feeds.parse_mb_txt(raw)
    vals = {r["value"] for r in rows}
    assert vals == {"aabbcc", "ddeeff"}
    assert all(r["type"] == "hash_sha256" for r in rows)


def test_parse_blocklistde_txt():
    """Lista piatta di IP (uno per riga), no API key. IPv6 fuori scope POE:
    va filtrato. Nessun campo threat/reference dal feed stesso -> reference
    costruito verso la pagina di ricerca pubblica di blocklist.de."""
    raw = (
        "1.0.164.165\n"
        "\n"                                            # riga vuota
        "2001:1388:4a01:1956:d010:a332:1b3c:4a8e\n"       # IPv6, va scartato
        "185.177.72.205\n"
    )
    rows = feeds.parse_blocklistde_txt(raw)
    vals = {r["value"] for r in rows}
    assert vals == {"1.0.164.165", "185.177.72.205"}
    assert all(r["type"] == "ipv4" for r in rows)
    assert all(r["threat"] is None for r in rows)
    hit = next(r for r in rows if r["value"] == "185.177.72.205")
    assert hit["reference"] == "https://www.blocklist.de/en/search.html?ip=185.177.72.205"


def test_format_parsers_dispatch():
    assert set(feeds.FORMAT_PARSERS) == {
        "threatfox_json", "urlhaus_csv", "feodo_json", "mb_txt", "blocklistde_txt",
    }


def test_load_feeds():
    fs = {f["name"]: f for f in feeds.load_feeds()}
    assert set(fs) == {"threatfox", "urlhaus", "feodo", "malwarebazaar", "blocklistde"}
    assert fs["threatfox"]["format"] == "threatfox_json"
    assert fs["malwarebazaar"]["ttl_hours"] == 24
    assert fs["blocklistde"]["format"] == "blocklistde_txt"
    assert all(f["format"] in feeds.FORMAT_PARSERS for f in feeds.load_feeds())


@pytest.mark.asyncio
async def test_download_feed(respx_mock):
    import httpx
    respx_mock.get("https://x.test/feed").mock(return_value=httpx.Response(200, text="hello"))
    assert await feeds.download_feed("https://x.test/feed") == "hello"
