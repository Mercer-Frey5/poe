"""Test per POST /e/{id}/lookup/{resource_id}/{entity_value} — interrogazione
on-demand (click esplicito) verso risorse no-API-key del catalogo OSINT:
crt.sh + urlscan.io (domain), urlscan.io (url), NVD (cve), Team Cymru (ipv4).
Nessuna persistenza.

Dispatch è per resource_id (id del catalogo), non per entity_type: un dominio
ha 2 lookup disponibili (crt.sh, urlscan.io), quindi il tipo da solo non basta
più a scegliere l'handler.

Mock a livello di app.main.<funzione> (non httpx): la logica di parsing rete è
già coperta da tests/test_live_lookup.py, qui testiamo solo il dispatch/wiring
della route e il rendering (formattato + raw)."""
import pytest
from fastapi.testclient import TestClient
from app import storage
from app.main import app
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "obs.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


async def _fake_crtsh_ok(domain: str) -> dict:
    return {"ok": True, "cert_count": 3, "subdomains": ["www.example.com"], "latest_issuer": "R3"}


async def _fake_nvd_ok(cve_id: str) -> dict:
    return {"ok": True, "description": "desc di test", "cvss_score": 9.8,
            "cvss_severity": "CRITICAL", "published": "2024-04-12T00:00:00.000"}


async def _fake_urlscan_ok(value: str, kind: str) -> dict:
    return {"ok": True, "total": 2, "scans": [
        {"page_url": "https://example.com/", "ip": "93.184.216.34", "asn": "AS15133",
         "date": "2026-06-01T10:00:00.000Z", "result_url": "https://urlscan.io/result/abc-123/"},
    ]}


async def _fake_cymru_ok(ip: str) -> dict:
    return {"ok": True, "asn": "15169", "as_name": "GOOGLE, US", "country": "US",
            "bgp_prefix": "8.8.8.0/24", "registry": "arin", "allocated": "1992-12-01"}


async def _fake_abuseipdb_ok(ip: str) -> dict:
    return {"ok": True, "abuse_score": 100, "total_reports": 42, "country": "CN",
            "isp": "Tencent Cloud", "domain": "tencent.com",
            "last_reported": "2026-06-01T00:00:00+00:00", "is_whitelisted": False}


async def _fake_virustotal_ok(value: str) -> dict:
    return {"ok": True, "malicious": 40, "suspicious": 2, "harmless": 20, "undetected": 8,
            "reputation": -15, "last_analysis_date": "2026-06-01T00:00:00+00:00",
            "meaningful_name": "trojan.exe", "categories": "trojan"}


async def _fake_shodan_ok(ip: str) -> dict:
    return {"ok": True, "ports": [22, 80, 443], "hostnames": ["scanme.nmap.org"],
            "org": "Linode, LLC", "isp": "Linode", "os": None,
            "vulns": ["CVE-2021-1234"], "products": ["OpenSSH", "nginx"]}


def test_lookup_domain_crtsh(client, monkeypatch):
    monkeypatch.setattr("app.main.crtsh_lookup", _fake_crtsh_ok)
    oid = storage.save_observation("x", [Entity("domain", "example.com")])

    r = client.post(f"/e/{oid}/lookup/site-crtsh/example.com")
    assert r.status_code == 200
    assert "www.example.com" in r.text
    # Niente wrapper .source-group nella risposta AJAX: il placeholder nel
    # template (el, target dello swap) è GIÀ quel wrapper — un doppio
    # wrapper annidava .source-group dentro .source-group ad ogni lookup.
    assert "source-group" not in r.text
    assert "source-header" in r.text
    assert "source-body" in r.text
    assert "btn-raw" in r.text
    assert "&quot;cert_count&quot;: 3" in r.text or '"cert_count": 3' in r.text


def test_lookup_includes_rank_when_provided(client, monkeypatch):
    """Le risorse esterne (live-lookup incluse) sono numerate #N come le
    altre fonti (estrattore/geo/RDAP/reputation) — il rank arriva come query
    param, calcolato dal template in base alla posizione nella sequenza."""
    monkeypatch.setattr("app.main.crtsh_lookup", _fake_crtsh_ok)
    oid = storage.save_observation("x", [Entity("domain", "example.com")])

    r = client.post(f"/e/{oid}/lookup/site-crtsh/example.com?rank=5")
    assert r.status_code == 200
    assert '<span class="source-rank">#5</span>' in r.text


def test_lookup_omits_rank_when_not_provided(client, monkeypatch):
    monkeypatch.setattr("app.main.crtsh_lookup", _fake_crtsh_ok)
    oid = storage.save_observation("x", [Entity("domain", "example.com")])

    r = client.post(f"/e/{oid}/lookup/site-crtsh/example.com")
    assert r.status_code == 200
    assert "source-rank" not in r.text


def test_lookup_cve_nvd(client, monkeypatch):
    monkeypatch.setattr("app.main.nvd_lookup", _fake_nvd_ok)
    oid = storage.save_observation("y", [Entity("cve", "CVE-2024-3400")])

    r = client.post(f"/e/{oid}/lookup/site-nvd-nist/CVE-2024-3400")
    assert r.status_code == 200
    assert "desc di test" in r.text
    assert "9.8" in r.text
    assert "CRITICAL" in r.text


def test_lookup_domain_urlscan(client, monkeypatch):
    monkeypatch.setattr("app.main.urlscan_lookup", _fake_urlscan_ok)
    oid = storage.save_observation("x", [Entity("domain", "example.com")])

    r = client.post(f"/e/{oid}/lookup/site-urlscan-domain/example.com")
    assert r.status_code == 200
    assert "93.184.216.34" in r.text
    assert "AS15133" in r.text
    assert '<a href="https://urlscan.io/result/abc-123/"' in r.text


def test_lookup_url_urlscan(client, monkeypatch):
    monkeypatch.setattr("app.main.urlscan_lookup", _fake_urlscan_ok)
    oid = storage.save_observation("x", [Entity("url", "https://example.com/path")])

    r = client.post(f"/e/{oid}/lookup/site-urlscan-url/https%3A%2F%2Fexample.com%2Fpath")
    assert r.status_code == 200
    assert "93.184.216.34" in r.text


def test_lookup_ipv4_cymru(client, monkeypatch):
    monkeypatch.setattr("app.main.cymru_asn_lookup", _fake_cymru_ok)
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])

    r = client.post(f"/e/{oid}/lookup/site-bgp-he-net/8.8.8.8")
    assert r.status_code == 200
    assert "15169" in r.text
    assert "GOOGLE, US" in r.text


def test_lookup_ipv4_abuseipdb(client, monkeypatch):
    monkeypatch.setattr("app.main.abuseipdb_lookup", _fake_abuseipdb_ok)
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])

    r = client.post(f"/e/{oid}/lookup/site-abuseipdb/8.8.8.8")
    assert r.status_code == 200
    assert "100/100" in r.text
    assert "Tencent Cloud" in r.text


def test_lookup_hash_virustotal(client, monkeypatch):
    monkeypatch.setattr("app.main.virustotal_lookup", _fake_virustotal_ok)
    sha256 = "aaaabbbbccccddddeeeeffff00001111aaaabbbbccccddddeeeeffff00001111"
    oid = storage.save_observation("x", [Entity("hash_sha256", sha256)])

    r = client.post(f"/e/{oid}/lookup/site-virustotal-search/{sha256}")
    assert r.status_code == 200
    assert "40/70 motori" in r.text
    assert "trojan.exe" in r.text


def test_lookup_ipv4_shodan(client, monkeypatch):
    monkeypatch.setattr("app.main.shodan_lookup", _fake_shodan_ok)
    oid = storage.save_observation("x", [Entity("ipv4", "45.33.32.156")])

    r = client.post(f"/e/{oid}/lookup/site-shodan/45.33.32.156")
    assert r.status_code == 200
    assert "22, 80, 443" in r.text
    assert "OpenSSH, nginx" in r.text
    assert "CVE-2021-1234" in r.text


def test_lookup_unsupported_resource(client):
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])

    r = client.post(f"/e/{oid}/lookup/site-does-not-exist/8.8.8.8")
    assert r.status_code == 400


def test_lookup_404_on_missing_observation(client):
    r = client.post("/e/99999/lookup/site-crtsh/example.com")
    assert r.status_code == 404


def test_lookup_error_result_renders_without_source_group(client, monkeypatch):
    async def _fake_crtsh_fail(domain: str) -> dict:
        return {"ok": False, "error": "boom"}

    monkeypatch.setattr("app.main.crtsh_lookup", _fake_crtsh_fail)
    oid = storage.save_observation("x", [Entity("domain", "example.com")])

    r = client.post(f"/e/{oid}/lookup/site-crtsh/example.com")
    assert r.status_code == 200
    assert "boom" in r.text


def test_lookup_error_keeps_rank_and_header_and_retry_button(client, monkeypatch):
    """L'errore ora usa la stessa forma (header + body) del successo: niente
    più perdita del rank/nome, e un bottone Riprova per rilanciare il lookup
    senza dover ricollassare/riespandere la card."""
    async def _fake_crtsh_fail(domain: str) -> dict:
        return {"ok": False, "error": "boom"}

    monkeypatch.setattr("app.main.crtsh_lookup", _fake_crtsh_fail)
    oid = storage.save_observation("x", [Entity("domain", "example.com")])

    r = client.post(f"/e/{oid}/lookup/site-crtsh/example.com?rank=3")
    assert r.status_code == 200
    assert '<span class="source-rank">#3</span>' in r.text
    assert "source-header" in r.text
    assert "btn-retry-lookup" in r.text
    assert "lookup-error" in r.text
