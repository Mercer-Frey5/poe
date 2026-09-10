"""Test per live_lookup.py — interrogazioni on-demand crt.sh/urlscan.io/NVD/
Team Cymru (no API key) + AbuseIPDB (con API key, da ABUSEIPDB_API_KEY). Mock
httpx con respx (stesso pattern di test_enrichers.py); Team Cymru usa whois
raw-socket (asyncio.open_connection), mockato con fake reader/writer."""
import asyncio

import pytest
import respx
import httpx

from app.live_lookup import (
    crtsh_lookup, nvd_lookup, urlscan_lookup, cymru_asn_lookup, abuseipdb_lookup,
    virustotal_lookup, shodan_lookup,
    gravatar_lookup, xposedornot_lookup, phone_info_lookup,
    threatfox_lookup, urlhaus_lookup, otx_lookup, hunter_verify_lookup,
)


# ── crt.sh ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_crtsh_lookup_success():
    respx.get("https://crt.sh/?q=example.com&output=json").mock(return_value=httpx.Response(200, json=[
        {
            "name_value": "www.example.com\nexample.com",
            "not_before": "2026-01-01T00:00:00",
            "issuer_name": "C=US, O=Let's Encrypt, CN=R3",
        },
        {
            "name_value": "mail.example.com",
            "not_before": "2026-03-01T00:00:00",
            "issuer_name": "C=US, O=Let's Encrypt, CN=R10",
        },
    ]))
    result = await crtsh_lookup("example.com")
    assert result["ok"] is True
    assert result["cert_count"] == 2
    assert "www.example.com" in result["subdomains"]
    assert "mail.example.com" in result["subdomains"]
    assert "example.com" in result["subdomains"]
    # not_before più recente (2026-03-01) -> issuer R10
    assert result["latest_issuer"] == "C=US, O=Let's Encrypt, CN=R10"


@pytest.mark.asyncio
@respx.mock
async def test_crtsh_lookup_failure_no_exception():
    respx.get("https://crt.sh/?q=example.com&output=json").mock(return_value=httpx.Response(500))
    result = await crtsh_lookup("example.com")
    assert result["ok"] is False
    assert "error" in result


@pytest.mark.asyncio
@respx.mock
async def test_crtsh_retries_on_502_then_succeeds(monkeypatch):
    """crt.sh restituisce spesso 502 intermittente (backend sovraccarico): il
    lookup ritenta AUTOMATICAMENTE e il secondo tentativo riesce, senza che
    l'utente debba cliccare 'Riprova'. Bug reale segnalato."""
    import app.live_lookup as ll
    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr(ll.asyncio, "sleep", _no_sleep)
    route = respx.get("https://crt.sh/?q=example.com&output=json").mock(side_effect=[
        httpx.Response(502),
        httpx.Response(200, json=[{
            "name_value": "example.com",
            "not_before": "2026-01-01T00:00:00",
            "issuer_name": "C=US, O=Let's Encrypt, CN=R3",
        }]),
    ])
    result = await crtsh_lookup("example.com")
    assert result["ok"] is True
    assert result["cert_count"] == 1
    assert route.call_count == 2   # ha ritentato dopo il 502


@pytest.mark.asyncio
@respx.mock
async def test_crtsh_gives_up_after_retries_all_502(monkeypatch):
    """Se crt.sh resta 502 su tutti i tentativi, dopo i retry restituisce un
    errore leggibile (non solleva) — il retry è limitato, non infinito."""
    import app.live_lookup as ll
    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr(ll.asyncio, "sleep", _no_sleep)
    route = respx.get("https://crt.sh/?q=example.com&output=json").mock(return_value=httpx.Response(502))
    result = await crtsh_lookup("example.com")
    assert result["ok"] is False
    assert "502" in result["error"]
    assert route.call_count == 3   # 1 tentativo + 2 retry


@pytest.mark.asyncio
@respx.mock
async def test_crtsh_lookup_404_means_no_certs_not_error():
    """crt.sh risponde 404 (non 200 con array vuoto) quando un dominio non
    ha nessun certificato TLS pubblico noto — è un risultato valido "nessun
    record", non un errore. Bug reale segnalato su un dominio esistente."""
    respx.get("https://crt.sh/?q=struthof.fr&output=json").mock(return_value=httpx.Response(404))
    result = await crtsh_lookup("struthof.fr")
    assert result["ok"] is True
    assert result["cert_count"] == 0
    assert result["subdomains"] == []


# ── NVD ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_nvd_lookup_success():
    respx.get(
        "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2024-3400"
    ).mock(return_value=httpx.Response(200, json={
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2024-3400",
                    "published": "2024-04-12T00:00:00.000",
                    "descriptions": [
                        {"lang": "en", "value": "A command injection vulnerability in PAN-OS."},
                        {"lang": "es", "value": "Una vulnerabilidad de inyección de comandos."},
                    ],
                    "metrics": {
                        "cvssMetricV31": [
                            {
                                "cvssData": {"baseScore": 10.0, "baseSeverity": "CRITICAL"},
                                "baseSeverity": "CRITICAL",
                            }
                        ]
                    },
                }
            }
        ]
    }))
    result = await nvd_lookup("CVE-2024-3400")
    assert result["ok"] is True
    assert result["description"] == "A command injection vulnerability in PAN-OS."
    assert result["cvss_score"] == 10.0
    assert result["cvss_severity"] == "CRITICAL"
    assert result["published"] == "2024-04-12T00:00:00.000"


@pytest.mark.asyncio
@respx.mock
async def test_nvd_lookup_not_found():
    """Zero vulnerabilità nella risposta = nessun record per questa CVE, non
    un errore: la richiesta è andata a buon fine, semplicemente non c'è
    niente da mostrare."""
    respx.get(
        "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-9999-9999"
    ).mock(return_value=httpx.Response(200, json={"vulnerabilities": []}))
    result = await nvd_lookup("CVE-9999-9999")
    assert result["ok"] is True
    assert result["description"]
    assert result["cvss_score"] is None


@pytest.mark.asyncio
@respx.mock
async def test_nvd_lookup_failure_no_exception():
    respx.get(
        "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2024-3400"
    ).mock(return_value=httpx.Response(500))
    result = await nvd_lookup("CVE-2024-3400")
    assert result["ok"] is False
    assert "error" in result


# ── urlscan.io ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_urlscan_lookup_domain_success():
    respx.get(url__regex=r"https://urlscan\.io/api/v1/search/.*").mock(
        return_value=httpx.Response(200, json={
            "total": 2,
            "results": [
                {
                    "_id": "11111111-2222-3333-4444-555555555555",
                    "page": {"url": "https://example.com/", "ip": "93.184.216.34", "asn": "AS15133"},
                    "task": {"time": "2026-06-01T10:00:00.000Z"},
                },
                {
                    "_id": "66666666-7777-8888-9999-000000000000",
                    "page": {"url": "https://example.com/old", "ip": "93.184.216.34", "asn": "AS15133"},
                    "task": {"time": "2026-01-01T10:00:00.000Z"},
                },
            ],
        })
    )
    result = await urlscan_lookup("example.com", "domain")
    assert result["ok"] is True
    assert result["total"] == 2
    assert result["scans"][0]["ip"] == "93.184.216.34"
    assert result["scans"][0]["asn"] == "AS15133"
    assert result["scans"][0]["page_url"] == "https://example.com/"
    assert result["scans"][0]["result_url"] == "https://urlscan.io/result/11111111-2222-3333-4444-555555555555/"


@pytest.mark.asyncio
@respx.mock
async def test_urlscan_lookup_url_no_results():
    respx.get(url__regex=r"https://urlscan\.io/api/v1/search/.*").mock(
        return_value=httpx.Response(200, json={"total": 0, "results": []})
    )
    result = await urlscan_lookup("https://example.com/nope", "url")
    assert result["ok"] is True
    assert result["total"] == 0
    assert result["scans"] == []


@pytest.mark.asyncio
@respx.mock
async def test_urlscan_lookup_failure_no_exception():
    respx.get(url__regex=r"https://urlscan\.io/api/v1/search/.*").mock(
        return_value=httpx.Response(500)
    )
    result = await urlscan_lookup("example.com", "domain")
    assert result["ok"] is False
    assert "error" in result


# ── Team Cymru (whois raw-socket, IP → ASN) ─────────────────────────────────

class _FakeWriter:
    def __init__(self):
        self.written = b""

    def write(self, data: bytes) -> None:
        self.written += data

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeReader:
    def __init__(self, data: bytes):
        self._data = data

    async def read(self, n: int = -1) -> bytes:
        return self._data


@pytest.mark.asyncio
async def test_cymru_asn_lookup_success(monkeypatch):
    async def fake_open_connection(host, port):
        assert host == "whois.cymru.com"
        assert port == 43
        return (
            _FakeReader(
                b"Bulk mode; whois.cymru.com [2026-01-01 00:00:00 +0000]\n"
                b"15169   | 8.8.8.8          | 8.8.8.0/24          | US | arin     "
                b"| 1992-12-01 | GOOGLE, US\n"
            ),
            _FakeWriter(),
        )

    monkeypatch.setattr("app.live_lookup.asyncio.open_connection", fake_open_connection)
    result = await cymru_asn_lookup("8.8.8.8")
    assert result["ok"] is True
    assert result["asn"] == "15169"
    assert result["as_name"] == "GOOGLE, US"
    assert result["country"] == "US"
    assert result["bgp_prefix"] == "8.8.8.0/24"
    assert result["registry"] == "arin"
    assert result["allocated"] == "1992-12-01"


@pytest.mark.asyncio
async def test_cymru_asn_lookup_not_found(monkeypatch):
    async def fake_open_connection(host, port):
        return (
            _FakeReader(
                b"Bulk mode; whois.cymru.com [2026-01-01 00:00:00 +0000]\n"
                b"NA      | 192.0.2.1        | NA                  | NA | NA       | NA         | NA\n"
            ),
            _FakeWriter(),
        )

    monkeypatch.setattr("app.live_lookup.asyncio.open_connection", fake_open_connection)
    result = await cymru_asn_lookup("192.0.2.1")
    # "NA" = IP non presente nelle tabelle BGP pubbliche: risultato valido
    # "nessun record", non un errore (la query a whois.cymru.com è riuscita).
    assert result["ok"] is True
    assert result["asn"] is None
    assert result["note"]


@pytest.mark.asyncio
async def test_cymru_asn_lookup_connection_failure_no_exception(monkeypatch):
    async def fake_open_connection(host, port):
        raise OSError("connection refused")

    monkeypatch.setattr("app.live_lookup.asyncio.open_connection", fake_open_connection)
    result = await cymru_asn_lookup("8.8.8.8")
    assert result["ok"] is False
    assert "error" in result


# ── AbuseIPDB (con API key, da ABUSEIPDB_API_KEY) ───────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_abuseipdb_lookup_success(monkeypatch):
    monkeypatch.setenv("ABUSEIPDB_API_KEY", "test-key-123")
    respx.get("https://api.abuseipdb.com/api/v2/check").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "ipAddress": "118.25.6.39", "abuseConfidenceScore": 100,
                "totalReports": 42, "countryCode": "CN", "isp": "Tencent Cloud",
                "domain": "tencent.com", "lastReportedAt": "2026-06-01T00:00:00+00:00",
                "isWhitelisted": False, "usageType": "Data Center/Web Hosting/Transit",
                "isTor": True, "numDistinctUsers": 7,
            }
        })
    )
    result = await abuseipdb_lookup("118.25.6.39")
    assert result["ok"] is True
    assert result["abuse_score"] == 100
    assert result["total_reports"] == 42
    assert result["country"] == "CN"
    assert result["isp"] == "Tencent Cloud"
    assert result["usage_type"] == "Data Center/Web Hosting/Transit"
    assert result["is_tor"] is True
    assert result["num_distinct_users"] == 7


@pytest.mark.asyncio
async def test_abuseipdb_lookup_no_key_configured(monkeypatch):
    monkeypatch.delenv("ABUSEIPDB_API_KEY", raising=False)
    result = await abuseipdb_lookup("118.25.6.39")
    assert result["ok"] is False
    assert "error" in result


@pytest.mark.asyncio
@respx.mock
async def test_abuseipdb_lookup_http_failure_no_exception(monkeypatch):
    monkeypatch.setenv("ABUSEIPDB_API_KEY", "test-key-123")
    respx.get("https://api.abuseipdb.com/api/v2/check").mock(return_value=httpx.Response(401))
    result = await abuseipdb_lookup("118.25.6.39")
    assert result["ok"] is False
    assert "AbuseIPDB" in result["error"] and "chiave rifiutata" in result["error"]


# ── VirusTotal (con API key, da VIRUSTOTAL_API_KEY) ─────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_virustotal_lookup_hash_success(monkeypatch):
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "test-key-123")
    sha256 = "aaaabbbbccccddddeeeeffff00001111aaaabbbbccccddddeeeeffff00001111"
    respx.get(f"https://www.virustotal.com/api/v3/files/{sha256}").mock(
        return_value=httpx.Response(200, json={
            "data": {"attributes": {
                "last_analysis_stats": {"malicious": 40, "suspicious": 2, "harmless": 20, "undetected": 8},
                "reputation": -15,
                "last_analysis_date": 1750000000,
                "meaningful_name": "trojan.exe",
                "categories": {"engineA": "trojan", "engineB": "trojan"},
                "popular_threat_classification": {"suggested_threat_label": "trojan.zbot/agent"},
                "type_description": "Win32 EXE",
                "tags": ["peexe", "trojan", "peexe"],
                "times_submitted": 1234,
            }}
        })
    )
    result = await virustotal_lookup(sha256)
    assert result["ok"] is True
    assert result["malicious"] == 40
    assert result["suspicious"] == 2
    assert result["reputation"] == -15
    assert result["meaningful_name"] == "trojan.exe"
    assert result["categories"] == "trojan"
    assert result["last_analysis_date"].startswith("2025-")
    assert result["threat_label"] == "trojan.zbot/agent"
    assert result["type_description"] == "Win32 EXE"
    assert result["tags"] == "peexe, trojan"
    assert result["times_submitted"] == 1234


@pytest.mark.asyncio
@respx.mock
async def test_virustotal_lookup_404_means_not_analyzed_not_error(monkeypatch):
    """VT risponde 404 quando l'IOC (url/hash/ip/dominio) non è mai stato
    analizzato: risultato valido "non presente", non un errore. Bug reale
    segnalato su URL e hash."""
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "test-key-123")
    sha256 = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    respx.get(f"https://www.virustotal.com/api/v3/files/{sha256}").mock(
        return_value=httpx.Response(404, json={"error": {"code": "NotFoundError"}}))
    result = await virustotal_lookup(sha256)
    assert result["ok"] is True
    assert result["found"] is False
    assert result.get("malicious") is None


@pytest.mark.asyncio
@respx.mock
async def test_virustotal_lookup_url_uses_base64_resource_id(monkeypatch):
    import base64
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "test-key-123")
    test_url = "http://malware-drop-example.top/payload.exe"
    resource_id = base64.urlsafe_b64encode(test_url.encode()).decode().strip("=")
    respx.get(f"https://www.virustotal.com/api/v3/urls/{resource_id}").mock(
        return_value=httpx.Response(200, json={
            "data": {"attributes": {
                "last_analysis_stats": {"malicious": 10, "suspicious": 0, "harmless": 60, "undetected": 5},
            }}
        })
    )
    result = await virustotal_lookup(test_url)
    assert result["ok"] is True
    assert result["malicious"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_virustotal_lookup_ipv4_uses_ip_addresses_endpoint(monkeypatch):
    """Un IPv4 (4 ottetti puri, non hash/URL) va su /ip_addresses/{ip}."""
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "test-key-123")
    respx.get("https://www.virustotal.com/api/v3/ip_addresses/93.184.216.34").mock(
        return_value=httpx.Response(200, json={
            "data": {"attributes": {
                "last_analysis_stats": {"malicious": 3, "suspicious": 1, "harmless": 70, "undetected": 6},
                "reputation": -5,
                "as_owner": "EDGECAST",
                "asn": 15133,
                "country": "US",
                "tags": ["cdn"],
            }}
        })
    )
    result = await virustotal_lookup("93.184.216.34")
    assert result["ok"] is True
    assert result["malicious"] == 3
    assert result["as_owner"] == "EDGECAST"
    assert result["asn"] == 15133
    assert result["country"] == "US"


@pytest.mark.asyncio
@respx.mock
async def test_virustotal_lookup_domain_uses_domains_endpoint(monkeypatch):
    """Un dominio nudo (no schema/path -> non è un URL) va su /domains/{domain}."""
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "test-key-123")
    respx.get("https://www.virustotal.com/api/v3/domains/malware-drop-example.top").mock(
        return_value=httpx.Response(200, json={
            "data": {"attributes": {
                "last_analysis_stats": {"malicious": 8, "suspicious": 0, "harmless": 10, "undetected": 60},
                "reputation": -30,
                "registrar": "NameCheap",
                "creation_date": 1700000000,
                "last_dns_records": [
                    {"type": "A", "value": "1.2.3.4"},
                    {"type": "MX", "value": "mail.malware-drop-example.top"},
                ],
            }}
        })
    )
    result = await virustotal_lookup("malware-drop-example.top")
    assert result["ok"] is True
    assert result["malicious"] == 8
    assert result["registrar"] == "NameCheap"
    assert result["creation_date"].startswith("2023-")
    assert "A 1.2.3.4" in result["last_dns_records"]


@pytest.mark.asyncio
async def test_virustotal_lookup_no_key_configured(monkeypatch):
    monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)
    result = await virustotal_lookup("aaaabbbbccccddddeeeeffff00001111aaaabbbbccccddddeeeeffff00001111")
    assert result["ok"] is False
    assert "error" in result


@pytest.mark.asyncio
@respx.mock
async def test_virustotal_lookup_http_failure_no_exception(monkeypatch):
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "test-key-123")
    sha256 = "aaaabbbbccccddddeeeeffff00001111aaaabbbbccccddddeeeeffff00001111"
    respx.get(f"https://www.virustotal.com/api/v3/files/{sha256}").mock(return_value=httpx.Response(401))
    result = await virustotal_lookup(sha256)
    assert result["ok"] is False
    assert "VirusTotal" in result["error"] and "chiave rifiutata" in result["error"]


# ── Shodan (con API key, da SHODAN_API_KEY) ──────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_shodan_lookup_host_success(monkeypatch):
    """Con membership, /shodan/host/{ip} risponde 200 con i dati ricchi
    (org/isp/os/banner): si usano quelli, InternetDB non viene interrogato."""
    monkeypatch.setenv("SHODAN_API_KEY", "test-key-123")
    respx.get("https://api.shodan.io/shodan/host/45.33.32.156").mock(
        return_value=httpx.Response(200, json={
            "ports": [22, 80, 443],
            "hostnames": ["scanme.nmap.org"],
            "org": "Linode, LLC",
            "isp": "Linode",
            "os": None,
            "vulns": ["CVE-2021-1234"],
            "tags": ["cloud"],
            "data": [{"product": "OpenSSH"}, {"product": "nginx"}, {"product": "OpenSSH"}],
        })
    )
    result = await shodan_lookup("45.33.32.156")
    assert result["ok"] is True
    assert result["ports"] == [22, 80, 443]
    assert result["hostnames"] == ["scanme.nmap.org"]
    assert result["org"] == "Linode, LLC"
    assert result["vulns"] == ["CVE-2021-1234"]
    assert result["products"] == ["OpenSSH", "nginx"]
    assert result["tags"] == ["cloud"]


@pytest.mark.asyncio
@respx.mock
async def test_shodan_lookup_no_key_uses_internetdb(monkeypatch):
    """Shodan è keyless in POE: senza SHODAN_API_KEY usa direttamente
    InternetDB (gratuito), la scheda funziona comunque."""
    monkeypatch.delenv("SHODAN_API_KEY", raising=False)
    respx.get("https://internetdb.shodan.io/45.33.32.156").mock(
        return_value=httpx.Response(200, json={
            "ip": "45.33.32.156", "ports": [22, 80], "hostnames": [],
            "cpes": [], "tags": ["cloud"], "vulns": [],
        })
    )
    result = await shodan_lookup("45.33.32.156")
    assert result["ok"] is True
    assert result["ports"] == [22, 80]
    assert result["tags"] == ["cloud"]


@pytest.mark.asyncio
@respx.mock
async def test_shodan_lookup_403_falls_back_to_internetdb(monkeypatch):
    """Caso reale segnalato: chiave valida sul tier gratuito -> /shodan/host
    risponde 403 (endpoint premium). Invece di fallire, si ricade su InternetDB
    (gratuito, senza key) e si restituiscono comunque porte/vulns/tag."""
    monkeypatch.setenv("SHODAN_API_KEY", "test-key-123")
    respx.get("https://api.shodan.io/shodan/host/132.144.1.4").mock(return_value=httpx.Response(403))
    respx.get("https://internetdb.shodan.io/132.144.1.4").mock(
        return_value=httpx.Response(200, json={
            "ip": "132.144.1.4", "ports": [80, 443],
            "hostnames": ["mail.mil"], "cpes": ["cpe:/a:apache:http_server"],
            "tags": ["cloud"], "vulns": ["CVE-2022-0001"],
        })
    )
    result = await shodan_lookup("132.144.1.4")
    assert result["ok"] is True
    assert result["ports"] == [80, 443]
    assert result["vulns"] == ["CVE-2022-0001"]
    assert result["tags"] == ["cloud"]
    assert result["products"] == ["cpe:/a:apache:http_server"]


@pytest.mark.asyncio
@respx.mock
async def test_shodan_lookup_internetdb_404_is_empty_not_error(monkeypatch):
    """InternetDB 404 = IP non nel dataset = nessun servizio esposto,
    non un errore: ok:True con liste vuote."""
    monkeypatch.setenv("SHODAN_API_KEY", "test-key-123")
    respx.get("https://api.shodan.io/shodan/host/8.8.8.8").mock(return_value=httpx.Response(403))
    respx.get("https://internetdb.shodan.io/8.8.8.8").mock(return_value=httpx.Response(404))
    result = await shodan_lookup("8.8.8.8")
    assert result["ok"] is True
    assert result["ports"] == []
    assert result["vulns"] == []


@pytest.mark.asyncio
@respx.mock
async def test_shodan_lookup_both_fail_no_key_leak(monkeypatch):
    """Se sia host che InternetDB falliscono, errore pulito senza URL/key."""
    monkeypatch.setenv("SHODAN_API_KEY", "test-key-123")
    respx.get("https://api.shodan.io/shodan/host/132.144.1.4").mock(return_value=httpx.Response(403))
    respx.get("https://internetdb.shodan.io/132.144.1.4").mock(return_value=httpx.Response(500))
    result = await shodan_lookup("132.144.1.4")
    assert result["ok"] is False
    assert "Shodan" in result["error"]
    assert "test-key-123" not in result["error"]  # niente key grezza nel messaggio


# ── Persone: Gravatar (email -> profilo pubblico, keyless) ───────────────────

@pytest.mark.asyncio
@respx.mock
async def test_gravatar_lookup_profile_found():
    import hashlib
    h = hashlib.md5(b"mario.rossi@example.com").hexdigest()
    respx.get(f"https://gravatar.com/{h}.json").mock(return_value=httpx.Response(200, json={
        "entry": [{"displayName": "Mario Rossi", "currentLocation": "Roma",
                   "accounts": [{"shortname": "github", "url": "https://github.com/mrossi"},
                                {"shortname": "twitter", "url": "https://twitter.com/mrossi"}]}]
    }))
    result = await gravatar_lookup("Mario.Rossi@example.com")  # case/space normalizzati
    assert result["ok"] is True
    assert result["has_profile"] is True
    assert result["display_name"] == "Mario Rossi"
    assert "github" in result["accounts"] and "twitter" in result["accounts"]


@pytest.mark.asyncio
@respx.mock
async def test_gravatar_lookup_404_means_no_profile_not_error():
    import hashlib
    h = hashlib.md5(b"nobody@example.com").hexdigest()
    respx.get(f"https://gravatar.com/{h}.json").mock(return_value=httpx.Response(404))
    result = await gravatar_lookup("nobody@example.com")
    assert result["ok"] is True
    assert result["has_profile"] is False


# ── Persone: XposedOrNot (email -> data-breach pubblici, keyless) ────────────

@pytest.mark.asyncio
@respx.mock
async def test_xposedornot_lookup_breached():
    respx.get(url__regex=r"https://api\.xposedornot\.com/v1/check-email/.*").mock(
        return_value=httpx.Response(200, json={"breaches": [["Adobe", "LinkedIn", "Dropbox"]]}))
    result = await xposedornot_lookup("mario.rossi@example.com")
    assert result["ok"] is True
    assert result["breached"] is True
    assert result["breach_count"] == 3
    assert "Adobe" in result["breaches"]


@pytest.mark.asyncio
@respx.mock
async def test_xposedornot_lookup_not_breached_404():
    respx.get(url__regex=r"https://api\.xposedornot\.com/v1/check-email/.*").mock(
        return_value=httpx.Response(404, json={"Error": "Not found"}))
    result = await xposedornot_lookup("clean@example.com")
    assert result["ok"] is True
    assert result["breached"] is False
    assert result["breach_count"] == 0


# ── Persone: phone_info (telefono -> regione/operatore/tipo, LOCALE offline) ──

@pytest.mark.asyncio
async def test_phone_info_lookup_valid_mobile():
    result = await phone_info_lookup("+393331234567")
    assert result["ok"] is True
    assert result["valid"] is True
    assert result["country_code"] == "+39"
    assert result["line_type"]  # es. "mobile"


@pytest.mark.asyncio
async def test_phone_info_lookup_unparsable():
    result = await phone_info_lookup("non-un-numero")
    assert result["ok"] is False
    assert "error" in result


# ── urlscan esteso a IP (kind="ip" -> q=ip:{value}) ──────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_urlscan_lookup_ip_uses_ip_query():
    respx.get(url__regex=r"https://urlscan\.io/api/v1/search/\?q=ip%3A.*").mock(
        return_value=httpx.Response(200, json={
            "total": 2,
            "results": [{"_id": "abc-1", "page": {"url": "http://x.test/", "ip": "1.2.3.4"},
                         "task": {"time": "2026-01-01T00:00:00Z"}}],
        }))
    result = await urlscan_lookup("1.2.3.4", "ip")
    assert result["ok"] is True
    assert result["total"] == 2
    assert result["scans"][0]["ip"] == "1.2.3.4"


# ── Threat-intel key-gated: ThreatFox / URLhaus (abuse.ch) / OTX / Hunter ────

@pytest.mark.asyncio
@respx.mock
async def test_threatfox_lookup_found(monkeypatch):
    monkeypatch.setenv("ABUSECH_API_KEY", "k")
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(return_value=httpx.Response(200, json={
        "query_status": "ok",
        "data": [{"malware_printable": "Cobalt Strike", "threat_type": "botnet_cc",
                  "confidence_level": 100, "first_seen": "2026-01-01 00:00:00 UTC",
                  "tags": ["cobaltstrike", "c2"]}]}))
    result = await threatfox_lookup("1.2.3.4")
    assert result["ok"] is True and result["found"] is True
    assert result["malware"] == "Cobalt Strike"
    assert result["confidence"] == 100
    assert "cobaltstrike" in result["tags"]


@pytest.mark.asyncio
@respx.mock
async def test_threatfox_lookup_no_result(monkeypatch):
    monkeypatch.setenv("ABUSECH_API_KEY", "k")
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(
        return_value=httpx.Response(200, json={"query_status": "no_result", "data": []}))
    result = await threatfox_lookup("8.8.8.8")
    assert result["ok"] is True and result["found"] is False


@pytest.mark.asyncio
async def test_threatfox_lookup_no_key(monkeypatch):
    monkeypatch.delenv("ABUSECH_API_KEY", raising=False)
    result = await threatfox_lookup("1.2.3.4")
    assert result["ok"] is False and "error" in result


@pytest.mark.asyncio
@respx.mock
async def test_urlhaus_lookup_host_found(monkeypatch):
    monkeypatch.setenv("ABUSECH_API_KEY", "k")
    respx.post("https://urlhaus-api.abuse.ch/v1/host/").mock(return_value=httpx.Response(200, json={
        "query_status": "ok", "threat": "malware_download", "url_status": "online",
        "url_count": "5", "tags": ["emotet"], "blacklists": {"spamhaus_dbl": "listed"}}))
    result = await urlhaus_lookup("bad.example.com")
    assert result["ok"] is True and result["found"] is True
    assert result["url_count"] == 5
    assert "emotet" in result["tags"]


@pytest.mark.asyncio
@respx.mock
async def test_urlhaus_lookup_url_endpoint(monkeypatch):
    monkeypatch.setenv("ABUSECH_API_KEY", "k")
    route = respx.post("https://urlhaus-api.abuse.ch/v1/url/").mock(
        return_value=httpx.Response(200, json={"query_status": "no_results"}))
    result = await urlhaus_lookup("http://bad.example.com/x")
    assert route.called  # ha usato l'endpoint /url/ per un URL
    assert result["ok"] is True and result["found"] is False


@pytest.mark.asyncio
@respx.mock
async def test_threatfox_lookup_bad_auth_key(monkeypatch):
    """abuse.ch risponde 403 + query_status=unknown_auth_key quando la Auth-Key
    non e' registrata. Non e' un limite di piano: le key sono gratuite. L'errore
    deve dirlo, altrimenti il 403 generico fa pensare a un servizio a pagamento."""
    monkeypatch.setenv("ABUSECH_API_KEY", "k")
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(
        return_value=httpx.Response(403, json={"query_status": "unknown_auth_key"}))
    result = await threatfox_lookup("1.2.3.4")
    assert result["ok"] is False
    assert "auth.abuse.ch" in result["error"]
    assert "Auth-Key" in result["error"], "deve dire QUALE campo copiare dal portale"


@pytest.mark.asyncio
@respx.mock
async def test_urlhaus_lookup_bad_auth_key(monkeypatch):
    """Stesso trattamento su URLhaus: condividono la Auth-Key."""
    monkeypatch.setenv("ABUSECH_API_KEY", "k")
    respx.post("https://urlhaus-api.abuse.ch/v1/host/").mock(
        return_value=httpx.Response(403, json={"query_status": "unknown_auth_key"}))
    result = await urlhaus_lookup("bad.example.com")
    assert result["ok"] is False
    assert "auth.abuse.ch" in result["error"]


@pytest.mark.asyncio
@respx.mock
async def test_threatfox_lookup_other_403_resta_errore_generico(monkeypatch):
    """Un 403 senza unknown_auth_key non deve prendere il messaggio Auth-Key:
    resta l'errore HTTP generico."""
    monkeypatch.setenv("ABUSECH_API_KEY", "k")
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(
        return_value=httpx.Response(403, json={"query_status": "rate_limited"}))
    result = await threatfox_lookup("1.2.3.4")
    assert result["ok"] is False
    assert "auth.abuse.ch" not in result["error"]


@pytest.mark.asyncio
@respx.mock
async def test_otx_lookup_ip_pulses(monkeypatch):
    monkeypatch.setenv("OTX_API_KEY", "k")
    respx.get("https://otx.alienvault.com/api/v1/indicators/IPv4/1.2.3.4/general").mock(
        return_value=httpx.Response(200, json={"pulse_info": {"count": 2, "pulses": [
            {"name": "Emotet C2", "tags": ["emotet"], "malware_families": [{"display_name": "Emotet"}]},
            {"name": "Generic scan", "tags": ["scan"], "malware_families": []}]}}))
    result = await otx_lookup("1.2.3.4")
    assert result["ok"] is True
    assert result["pulse_count"] == 2
    assert "Emotet C2" in result["pulses"]
    assert "Emotet" in result["malware_families"]


@pytest.mark.asyncio
async def test_otx_lookup_no_key(monkeypatch):
    monkeypatch.delenv("OTX_API_KEY", raising=False)
    result = await otx_lookup("1.2.3.4")
    assert result["ok"] is False and "error" in result


@pytest.mark.asyncio
@respx.mock
async def test_hunter_verify_lookup(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "k")
    respx.get(url__regex=r"https://api\.hunter\.io/v2/email-verifier.*").mock(
        return_value=httpx.Response(200, json={"data": {
            "status": "valid", "result": "deliverable", "score": 92,
            "disposable": False, "webmail": True}}))
    result = await hunter_verify_lookup("mario@example.com")
    assert result["ok"] is True
    assert result["status"] == "valid"
    assert result["score"] == 92
    assert result["disposable"] is False


@pytest.mark.asyncio
@respx.mock
async def test_hunter_400_error_does_not_leak_api_key(monkeypatch):
    """Caso reale: Hunter mette la key in query string (?api_key=), e un 400
    faceva trapelare l'URL completo (con la key) nel messaggio d'errore. Il
    messaggio NON deve contenere né la key né l'URL."""
    monkeypatch.setenv("HUNTER_API_KEY", "super-secret-key-123")
    respx.get(url__regex=r"https://api\.hunter\.io/v2/email-verifier.*").mock(
        return_value=httpx.Response(400, json={"errors": [{"details": "invalid"}]}))
    result = await hunter_verify_lookup("giulia@example.org")
    assert result["ok"] is False
    assert "super-secret-key-123" not in result["error"]
    assert "api_key" not in result["error"]
    assert "hunter.io" not in result["error"].lower()
    assert "Hunter" in result["error"]


# ── EmailRep.io ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_emailrep_lookup_success():
    from app.live_lookup import emailrep_lookup
    respx.get("https://emailrep.io/mario@example.com").mock(return_value=httpx.Response(200, json={
        "email": "mario@example.com", "reputation": "high", "suspicious": False,
        "references": 42, "details": {
            "credentials_leaked": True, "data_breach": True, "malicious_activity": False,
            "last_seen": "2025-11-01", "profiles": ["twitter", "github"],
            "disposable": False, "free_provider": True, "deliverable": True, "blacklisted": False,
        }}))
    r = await emailrep_lookup("mario@example.com")
    assert r["ok"] is True
    assert r["reputation"] == "high"
    assert r["credentials_leaked"] is True
    assert r["profiles"] == "twitter, github"


@pytest.mark.asyncio
@respx.mock
async def test_emailrep_lookup_rate_limited_no_key_leak():
    from app.live_lookup import emailrep_lookup
    respx.get("https://emailrep.io/x@y.com").mock(return_value=httpx.Response(429, json={}))
    r = await emailrep_lookup("x@y.com")
    assert r["ok"] is False
    assert "EMAILREP_API_KEY" in r["error"]


# ── Hudson Rock (email) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_hudsonrock_email_compromised():
    from app.live_lookup import hudsonrock_email_lookup
    respx.get("https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email").mock(
        return_value=httpx.Response(200, json={"message": "compromised",
            "stealers": [{"stealer_family": "RedLine", "date_compromised": "2024-05-02T00:00:00Z"}]}))
    r = await hudsonrock_email_lookup("mario@example.com")
    assert r["ok"] is True
    assert r["compromised"] is True
    assert r["stealer_count"] == 1
    assert "RedLine" in r["stealers"]


@pytest.mark.asyncio
@respx.mock
async def test_hudsonrock_email_clean():
    from app.live_lookup import hudsonrock_email_lookup
    respx.get("https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email").mock(
        return_value=httpx.Response(200, json={"message": "not compromised", "stealers": []}))
    r = await hudsonrock_email_lookup("mario@example.com")
    assert r["ok"] is True
    assert r["compromised"] is False
    assert r["stealer_count"] == 0


# ── Hudson Rock (username) ──────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_hudsonrock_username_compromised():
    from app.live_lookup import hudsonrock_username_lookup
    respx.get("https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-username").mock(
        return_value=httpx.Response(200, json={"message": "compromised",
            "stealers": [{"stealer_family": "Raccoon", "date_compromised": "2023-01-10T00:00:00Z"}]}))
    r = await hudsonrock_username_lookup("giuliab")
    assert r["ok"] is True and r["compromised"] is True and r["stealer_count"] == 1


# ── GitHub API ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_github_api_found():
    from app.live_lookup import github_api_lookup
    respx.get("https://api.github.com/users/octocat").mock(return_value=httpx.Response(200, json={
        "name": "The Octocat", "company": "@github", "blog": "https://github.blog",
        "twitter_username": "octo", "email": None, "bio": "hi", "location": "SF",
        "public_repos": 8, "followers": 1000, "created_at": "2011-01-25T18:44:36Z",
        "html_url": "https://github.com/octocat"}))
    r = await github_api_lookup("octocat")
    assert r["ok"] is True and r["found"] is True
    assert r["name"] == "The Octocat"
    assert r["created_at"] == "2011-01-25"


@pytest.mark.asyncio
@respx.mock
async def test_github_api_not_found():
    from app.live_lookup import github_api_lookup
    respx.get("https://api.github.com/users/nope").mock(return_value=httpx.Response(404, json={}))
    r = await github_api_lookup("nope")
    assert r["ok"] is True and r["found"] is False


# ── Keybase API ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_keybase_api_found():
    from app.live_lookup import keybase_api_lookup
    respx.get("https://keybase.io/_/api/1.0/user/lookup.json").mock(return_value=httpx.Response(200, json={
        "status": {"code": 0}, "them": [{
            "basics": {"username": "chris"},
            "profile": {"full_name": "Chris C", "location": "NY"},
            "proofs_summary": {"all": [
                {"proof_type": "twitter", "nametag": "malgorithms"},
                {"proof_type": "github", "nametag": "chris"}]},
            "public_keys": {"pgp_public_keys": ["-----BEGIN..."]}}]}))
    r = await keybase_api_lookup("chris")
    assert r["ok"] is True and r["found"] is True
    assert "twitter:malgorithms" in r["accounts"]
    assert r["pgp_keys"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_keybase_api_not_found():
    from app.live_lookup import keybase_api_lookup
    respx.get("https://keybase.io/_/api/1.0/user/lookup.json").mock(
        return_value=httpx.Response(200, json={"status": {"code": 0}, "them": [None]}))
    r = await keybase_api_lookup("nope")
    assert r["ok"] is True and r["found"] is False


# ── GitLab API ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_gitlab_api_found():
    from app.live_lookup import gitlab_api_lookup
    respx.get("https://gitlab.com/api/v4/users").mock(return_value=httpx.Response(200, json=[{
        "name": "Jane", "state": "active", "bio": "dev", "location": "Berlin",
        "website_url": "https://jane.dev", "twitter": "janedev", "linkedin": "jane",
        "created_at": "2015-03-04T00:00:00Z", "web_url": "https://gitlab.com/jane"}]))
    r = await gitlab_api_lookup("jane")
    assert r["ok"] is True and r["found"] is True
    assert r["name"] == "Jane" and r["created_at"] == "2015-03-04"


@pytest.mark.asyncio
@respx.mock
async def test_gitlab_api_not_found():
    from app.live_lookup import gitlab_api_lookup
    respx.get("https://gitlab.com/api/v4/users").mock(return_value=httpx.Response(200, json=[]))
    r = await gitlab_api_lookup("nope")
    assert r["ok"] is True and r["found"] is False


# ── Reddit API ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_reddit_api_found():
    from app.live_lookup import reddit_api_lookup
    respx.get("https://www.reddit.com/user/spez/about.json").mock(return_value=httpx.Response(200, json={
        "data": {"name": "spez", "created_utc": 1118030400, "link_karma": 100,
                 "comment_karma": 5000, "verified": True, "is_mod": True}}))
    r = await reddit_api_lookup("spez")
    assert r["ok"] is True and r["found"] is True
    assert r["comment_karma"] == 5000
    assert r["created"] == "2005-06-06"


@pytest.mark.asyncio
@respx.mock
async def test_reddit_api_not_found():
    from app.live_lookup import reddit_api_lookup
    respx.get("https://www.reddit.com/user/nope/about.json").mock(return_value=httpx.Response(404, json={}))
    r = await reddit_api_lookup("nope")
    assert r["ok"] is True and r["found"] is False



# ── IPQualityScore (email) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ipqs_email_no_key():
    from app.live_lookup import ipqs_email_lookup
    r = await ipqs_email_lookup("mario@example.com")
    assert r["ok"] is False
    assert "IPQS_API_KEY" in r["error"]


@pytest.mark.asyncio
@respx.mock
async def test_ipqs_email_success(monkeypatch):
    monkeypatch.setenv("IPQS_API_KEY", "test-key-123")
    from app.live_lookup import ipqs_email_lookup
    respx.get("https://ipqualityscore.com/api/json/email/test-key-123/mario@example.com").mock(
        return_value=httpx.Response(200, json={
            "success": True, "valid": True, "disposable": False,
            "deliverability": "high", "fraud_score": 12, "recent_abuse": False,
            "leaked": True, "first_seen": {"human": "3 years ago"}}))
    r = await ipqs_email_lookup("mario@example.com")
    assert r["ok"] is True
    assert r["fraud_score"] == 12
    assert r["leaked"] is True


@pytest.mark.asyncio
@respx.mock
async def test_ipqs_email_error_hides_api_key(monkeypatch):
    monkeypatch.setenv("IPQS_API_KEY", "super-secret-key-123")
    from app.live_lookup import ipqs_email_lookup
    respx.get("https://ipqualityscore.com/api/json/email/super-secret-key-123/mario@example.com").mock(
        return_value=httpx.Response(401, json={"message": "invalid key"}))
    r = await ipqs_email_lookup("mario@example.com")
    assert r["ok"] is False
    assert "super-secret-key-123" not in r["error"]


# ── IPQualityScore (phone) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ipqs_phone_no_key():
    from app.live_lookup import ipqs_phone_lookup
    r = await ipqs_phone_lookup("+393512345678")
    assert r["ok"] is False
    assert "IPQS_API_KEY" in r["error"]


@pytest.mark.asyncio
@respx.mock
async def test_ipqs_phone_success(monkeypatch):
    monkeypatch.setenv("IPQS_API_KEY", "test-key-123")
    from app.live_lookup import ipqs_phone_lookup
    respx.get("https://ipqualityscore.com/api/json/phone/test-key-123/+393512345678").mock(
        return_value=httpx.Response(200, json={
            "success": True, "valid": True, "active": True, "fraud_score": 5,
            "recent_abuse": False, "line_type": "Mobile", "carrier": "TIM",
            "leaked": False, "risky": False}))
    r = await ipqs_phone_lookup("+393512345678")
    assert r["ok"] is True
    assert r["carrier"] == "TIM"
    assert r["line_type"] == "Mobile"


# ── Numverify ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_numverify_no_key():
    from app.live_lookup import numverify_lookup
    r = await numverify_lookup("+393512345678")
    assert r["ok"] is False
    assert "NUMVERIFY_API_KEY" in r["error"]


@pytest.mark.asyncio
@respx.mock
async def test_numverify_success(monkeypatch):
    monkeypatch.setenv("NUMVERIFY_API_KEY", "test-key-123")
    from app.live_lookup import numverify_lookup
    respx.get("https://apilayer.net/api/validate").mock(return_value=httpx.Response(200, json={
        "valid": True, "number": "393512345678", "country_code": "IT",
        "location": "", "carrier": "TIM", "line_type": "mobile"}))
    r = await numverify_lookup("+393512345678")
    assert r["ok"] is True
    assert r["valid"] is True
    assert r["carrier"] == "TIM"


@pytest.mark.asyncio
@respx.mock
async def test_numverify_error_hides_api_key(monkeypatch):
    monkeypatch.setenv("NUMVERIFY_API_KEY", "super-secret-key-123")
    from app.live_lookup import numverify_lookup
    respx.get("https://apilayer.net/api/validate").mock(
        return_value=httpx.Response(200, json={"success": False, "error": {"info": "Invalid access key"}}))
    r = await numverify_lookup("+393512345678")
    assert r["ok"] is False
    assert "super-secret-key-123" not in r["error"]


# ── WhatsMyName (presenza username, dataset locale) ─────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_whatsmyname_lookup_finds_matches(monkeypatch, tmp_path):
    import json
    from app import live_lookup
    fixture = {
        "sites": [
            {"name": "SiteA", "uri_check": "https://a.example/{account}",
             "e_code": 200, "e_string": "profile-header", "m_string": "", "m_code": 404},
            {"name": "SiteB", "uri_check": "https://b.example/u/{account}",
             "e_code": 200, "e_string": "user-exists", "m_string": "", "m_code": 404},
        ]
    }
    wmn_file = tmp_path / "wmn-data.json"
    wmn_file.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(live_lookup, "_WMN_DATA_PATH", wmn_file)

    respx.get("https://a.example/octocat").mock(
        return_value=httpx.Response(200, text="<div class='profile-header'>octocat</div>"))
    respx.get("https://b.example/u/octocat").mock(
        return_value=httpx.Response(404, text="not found"))

    r = await live_lookup.whatsmyname_lookup("octocat")
    assert r["ok"] is True
    assert r["checked"] == 2
    assert r["total_sites"] == 2
    names = [f["name"] for f in r["found"]]
    assert names == ["SiteA"]
    assert r["found"][0]["url"] == "https://a.example/octocat"


@pytest.mark.asyncio
@respx.mock
async def test_whatsmyname_lookup_no_matches(monkeypatch, tmp_path):
    import json
    from app import live_lookup
    fixture = {"sites": [
        {"name": "SiteA", "uri_check": "https://a.example/{account}",
         "e_code": 200, "e_string": "profile-header", "m_string": "", "m_code": 404},
    ]}
    wmn_file = tmp_path / "wmn-data.json"
    wmn_file.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(live_lookup, "_WMN_DATA_PATH", wmn_file)
    respx.get("https://a.example/nobody12345").mock(return_value=httpx.Response(404))
    r = await live_lookup.whatsmyname_lookup("nobody12345")
    assert r["ok"] is True
    assert r["found"] == []
    assert r["checked"] == 1


@pytest.mark.asyncio
async def test_whatsmyname_lookup_request_errors_are_skipped_not_fatal(monkeypatch, tmp_path):
    import json
    from app import live_lookup
    fixture = {"sites": [
        {"name": "Unreachable", "uri_check": "https://does-not-exist.invalid/{account}",
         "e_code": 200, "e_string": "x", "m_string": "", "m_code": 404},
    ]}
    wmn_file = tmp_path / "wmn-data.json"
    wmn_file.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(live_lookup, "_WMN_DATA_PATH", wmn_file)
    r = await live_lookup.whatsmyname_lookup("someuser")
    assert r["ok"] is True
    assert r["found"] == []
    assert r["checked"] == 1


@pytest.mark.asyncio
async def test_whatsmyname_lookup_skips_post_based_sites(monkeypatch, tmp_path):
    # ~21/719 siti reali usano POST (post_body/headers, niente {account} in
    # uri_check) — il checker minimo li salta: non contano in "checked", non
    # sollevano errori.
    import json
    from app import live_lookup
    fixture = {"sites": [
        {"name": "PostOnly", "uri_check": "https://api.example/check",
         "post_body": "username={account}", "e_code": 200, "e_string": "ok",
         "m_string": "", "m_code": 404},
    ]}
    wmn_file = tmp_path / "wmn-data.json"
    wmn_file.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(live_lookup, "_WMN_DATA_PATH", wmn_file)
    r = await live_lookup.whatsmyname_lookup("someuser")
    assert r["ok"] is True
    assert r["found"] == []
    assert r["checked"] == 0
    assert r["total_sites"] == 1


# ── Holehe (email -> account registrati, subprocess) ────────────────────────
# ATTENZIONE: nessuno di questi test invoca il vero binario holehe (spammerebbe
# ~120 siti reali con flussi di password-recovery). _run_holehe_subprocess è
# sempre monkeypatchato con una fake che scrive un CSV di fixture nella cwd
# ricevuta, esattamente come farebbe il binario reale con -C.

_HOLEHE_CSV_HEADER = "name,domain,rateLimit,error,exists,emailrecovery,phoneNumber,others\n"


def _write_fake_holehe_csv(cwd, email, rows_csv_body):
    from pathlib import Path
    csv_path = Path(cwd) / f"holehe_1700000000_{email}_results.csv"
    csv_path.write_text(_HOLEHE_CSV_HEADER + rows_csv_body, encoding="utf-8")


@pytest.mark.asyncio
async def test_holehe_lookup_finds_accounts(monkeypatch):
    from app import live_lookup

    async def fake_run(email, cwd, timeout=60.0):
        _write_fake_holehe_csv(cwd, email,
            "github,github.com,False,False,True,,,{}\n"
            "twitter,twitter.com,False,False,False,,,{}\n"
            "adobe,adobe.com,False,False,True,,,{}\n")

    monkeypatch.setattr(live_lookup, "_run_holehe_subprocess", fake_run)
    r = await live_lookup.holehe_lookup("mario@example.com")
    assert r["ok"] is True
    assert r["checked"] == 3
    sites = sorted(f["site"] for f in r["found"])
    assert sites == ["adobe", "github"]


@pytest.mark.asyncio
async def test_holehe_lookup_no_accounts_found(monkeypatch):
    from app import live_lookup

    async def fake_run(email, cwd, timeout=60.0):
        _write_fake_holehe_csv(cwd, email, "github,github.com,False,False,False,,,{}\n")

    monkeypatch.setattr(live_lookup, "_run_holehe_subprocess", fake_run)
    r = await live_lookup.holehe_lookup("nobody@example.com")
    assert r["ok"] is True
    assert r["found"] == []
    assert r["checked"] == 1


@pytest.mark.asyncio
async def test_holehe_lookup_timeout(monkeypatch):
    from app import live_lookup

    async def fake_run(email, cwd, timeout=60.0):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(live_lookup, "_run_holehe_subprocess", fake_run)
    r = await live_lookup.holehe_lookup("mario@example.com")
    assert r["ok"] is False
    assert "timeout" in r["error"].lower()


@pytest.mark.asyncio
async def test_holehe_lookup_binary_not_installed(monkeypatch):
    from app import live_lookup

    async def fake_run(email, cwd, timeout=60.0):
        raise FileNotFoundError("holehe non trovato")

    monkeypatch.setattr(live_lookup, "_run_holehe_subprocess", fake_run)
    r = await live_lookup.holehe_lookup("mario@example.com")
    assert r["ok"] is False
    assert "non installat" in r["error"].lower()


@pytest.mark.asyncio
async def test_holehe_lookup_no_csv_produced(monkeypatch):
    from app import live_lookup

    async def fake_run(email, cwd, timeout=60.0):
        pass  # non scrive nessun file

    monkeypatch.setattr(live_lookup, "_run_holehe_subprocess", fake_run)
    r = await live_lookup.holehe_lookup("mario@example.com")
    assert r["ok"] is False
    assert "nessun" in r["error"].lower() or "output" in r["error"].lower()


# ── Test-key: verifica IPQS/Numverify (sezione /settings/api) ───────────────

@pytest.mark.asyncio
@respx.mock
async def test_ipqs_key_valid():
    from app.live_lookup import test_ipqs_key
    respx.get("https://ipqualityscore.com/api/json/email/test-key-123/test@example.com").mock(
        return_value=httpx.Response(200, json={"success": True, "valid": True}))
    r = await test_ipqs_key("test-key-123")
    assert r["ok"] is True


@pytest.mark.asyncio
@respx.mock
async def test_ipqs_key_invalid():
    from app.live_lookup import test_ipqs_key
    respx.get("https://ipqualityscore.com/api/json/email/bad-key/test@example.com").mock(
        return_value=httpx.Response(200, json={"success": False, "message": "invalid key"}))
    r = await test_ipqs_key("bad-key")
    assert r["ok"] is False


@pytest.mark.asyncio
@respx.mock
async def test_numverify_key_valid():
    from app.live_lookup import test_numverify_key
    respx.get("https://apilayer.net/api/validate").mock(
        return_value=httpx.Response(200, json={"valid": True, "number": "14158586273"}))
    r = await test_numverify_key("test-key-123")
    assert r["ok"] is True


@pytest.mark.asyncio
@respx.mock
async def test_numverify_key_invalid():
    from app.live_lookup import test_numverify_key
    respx.get("https://apilayer.net/api/validate").mock(
        return_value=httpx.Response(200, json={"success": False, "error": {"info": "Invalid access key"}}))
    r = await test_numverify_key("bad-key")
    assert r["ok"] is False


# ── Verifica della Auth-Key dal pannello "Servizi & API" ────────────────────
#
# Le funzioni `test_*_key` di live_lookup.py sono quelle dietro il pulsante
# "Testa". Si importano via modulo, non per nome: chiamandole `test_...`, un
# `from app.live_lookup import test_abusech_key` le farebbe raccogliere da
# pytest come se fossero test, con l'argomento `api_key` scambiato per una
# fixture. E' anche il motivo per cui erano rimaste tutte senza copertura.

import app.live_lookup as live_lookup   # noqa: E402


@pytest.mark.asyncio
@respx.mock
async def test_verifica_chiave_abusech_valida():
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(
        return_value=httpx.Response(200, json={"query_status": "ok", "data": []}))
    assert (await live_lookup.test_abusech_key("k"))["ok"] is True


@pytest.mark.asyncio
@respx.mock
async def test_verifica_chiave_abusech_non_riconosciuta_e_esplicita():
    """Il pannello dove si incolla la chiave dava il messaggio PIU' povero di
    tutti ("chiave non valida"), mentre il lookup spiegava dove generarla:
    esattamente al contrario di quel che serve a chi sta configurando."""
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(
        return_value=httpx.Response(403, json={"query_status": "unknown_auth_key"}))
    r = await live_lookup.test_abusech_key("k")
    assert r["ok"] is False
    assert "auth.abuse.ch" in r["error"]


@pytest.mark.asyncio
@respx.mock
async def test_verifica_chiave_abusech_403_generico():
    """Un 403 che non sia unknown_auth_key non deve prendere lo stesso
    messaggio: la causa e' un'altra e mandare l'utente a rigenerare la chiave
    lo farebbe girare a vuoto."""
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(
        return_value=httpx.Response(403, text="Forbidden"))
    r = await live_lookup.test_abusech_key("k")
    assert r["ok"] is False
    assert "auth.abuse.ch" not in r["error"]


@pytest.mark.asyncio
@respx.mock
async def test_verifica_chiave_abusech_errore_di_rete():
    respx.post("https://threatfox-api.abuse.ch/api/v1/").mock(
        side_effect=httpx.ConnectError("giu'"))
    assert (await live_lookup.test_abusech_key("k"))["ok"] is False


# ── Errori distinguibili: quota, chiave, piano ──────────────────────────────
#
# Numverify e IPQS segnalano cause DIVERSE che richiedono azioni diverse:
# rigenerare una chiave, aspettare il mese nuovo, cambiare piano. Ridurle tutte
# a un messaggio solo manda l'utente a caccia della cosa sbagliata — e su un
# free tier da 100 richieste al mese (Numverify) o 35 al giorno (IPQS), la
# causa piu' probabile non e' la chiave: e' la quota.

@pytest.mark.asyncio
@respx.mock
async def test_numverify_quota_esaurita(monkeypatch):
    """Numverify usa status HTTP veri. Con raise_for_status() prima del parsing,
    un 429 diventava "errore di rete o timeout": la diagnosi opposta."""
    monkeypatch.setenv("NUMVERIFY_API_KEY", "k")
    respx.get("https://apilayer.net/api/validate").mock(return_value=httpx.Response(
        429, json={"success": False, "error": {"code": 104, "type": "usage_limit_reached",
                                               "info": "monthly usage limit reached"}}))
    r = await live_lookup.numverify_lookup("+393512345678")
    assert r["ok"] is False
    assert "quota" in r["error"].lower()
    assert "rete" not in r["error"].lower(), "la rete non c'entra nulla"


@pytest.mark.asyncio
@respx.mock
async def test_numverify_chiave_non_valida(monkeypatch):
    monkeypatch.setenv("NUMVERIFY_API_KEY", "k")
    respx.get("https://apilayer.net/api/validate").mock(return_value=httpx.Response(
        401, json={"success": False, "error": {"code": 101, "type": "invalid_access_key",
                                               "info": "You have not supplied a valid API Access Key."}}))
    r = await live_lookup.numverify_lookup("+393512345678")
    assert r["ok"] is False
    assert "chiave" in r["error"].lower()


@pytest.mark.asyncio
@respx.mock
async def test_numverify_https_non_nel_piano(monkeypatch):
    """Su alcuni piani apilayer https e' riservato ai paganti. Va detto, non
    fatto passare per un guasto."""
    monkeypatch.setenv("NUMVERIFY_API_KEY", "k")
    respx.get("https://apilayer.net/api/validate").mock(return_value=httpx.Response(
        403, json={"success": False, "error": {"code": 105, "type": "https_access_restricted",
                                               "info": "HTTPS not supported on this plan"}}))
    r = await live_lookup.numverify_lookup("+393512345678")
    assert r["ok"] is False
    assert "https" in r["error"].lower()


@pytest.mark.asyncio
@respx.mock
async def test_numverify_errore_di_rete_resta_tale(monkeypatch):
    """Il messaggio "rete o timeout" deve restare per i guasti che lo sono."""
    monkeypatch.setenv("NUMVERIFY_API_KEY", "k")
    respx.get("https://apilayer.net/api/validate").mock(side_effect=httpx.ConnectError("giu'"))
    r = await live_lookup.numverify_lookup("+393512345678")
    assert r["ok"] is False
    assert "rete" in r["error"].lower() or "timeout" in r["error"].lower()


@pytest.mark.asyncio
@respx.mock
async def test_ipqs_riporta_il_motivo_vero(monkeypatch):
    """IPQS risponde 200 con success:false e un campo `message` che dice la
    causa. Attribuirla sempre alla chiave e' fuorviante: con 35 lookup al
    giorno, l'esaurimento credito e' lo scenario piu' probabile."""
    monkeypatch.setenv("IPQS_API_KEY", "k")
    respx.get(url__regex=r"https://.*ipqualityscore\.com/api/json/phone/.*").mock(
        return_value=httpx.Response(200, json={
            "success": False, "message": "Insufficient credits for this query",
            "request_id": "4OTORR352FU0p"}))
    r = await live_lookup.ipqs_phone_lookup("+393512345678")
    assert r["ok"] is False
    assert "credit" in r["error"].lower() or "credito" in r["error"].lower()


@pytest.mark.asyncio
@respx.mock
async def test_ipqs_non_perde_il_request_id(monkeypatch):
    """IPQS chiede il request_id per l'assistenza: buttarlo via costa un giro
    di richieste in piu' quando serve aprire un ticket."""
    monkeypatch.setenv("IPQS_API_KEY", "k")
    respx.get(url__regex=r"https://.*ipqualityscore\.com/api/json/email/.*").mock(
        return_value=httpx.Response(200, json={
            "success": False, "message": "Insufficient credits", "request_id": "ABC123"}))
    r = await live_lookup.ipqs_email_lookup("a@b.com")
    assert "ABC123" in r["error"]


@pytest.mark.asyncio
@respx.mock
async def test_verifica_chiave_numverify_distingue_le_cause():
    """Il pannello diceva "risposta inattesa (401)" a chi aveva sbagliato la
    chiave, e la stessa frase a chi aveva solo finito la quota."""
    respx.get("https://apilayer.net/api/validate").mock(return_value=httpx.Response(
        401, json={"success": False, "error": {"code": 101, "type": "invalid_access_key",
                                               "info": "no key"}}))
    r = await live_lookup.test_numverify_key("k")
    assert r["ok"] is False and "chiave" in r["error"].lower()

    respx.get("https://apilayer.net/api/validate").mock(return_value=httpx.Response(
        429, json={"success": False, "error": {"code": 104, "type": "usage_limit_reached",
                                               "info": "limit"}}))
    r = await live_lookup.test_numverify_key("k")
    assert r["ok"] is False and "quota" in r["error"].lower()


def test_ipqs_segue_i_redirect():
    """httpx non segue i redirect di default. Se IPQS estendesse il redirect
    canonico verso www ai path /api/, raise_for_status non scatterebbe (301 non
    e' 4xx), resp.json() esploderebbe sul corpo del redirect e OGNI lookup IPQS
    diventerebbe "errore di rete o timeout". Altrove nel file il flag c'e' gia'."""
    import inspect
    src = inspect.getsource(live_lookup)
    blocco = src[src.index("async def ipqs_email_lookup"):src.index("async def numverify_lookup")]
    assert blocco.count("follow_redirects=True") >= 2, \
        "le chiamate IPQS devono seguire il redirect canonico verso www"

