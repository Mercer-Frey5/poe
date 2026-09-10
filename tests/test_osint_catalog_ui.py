"""Task 2: sezione 'Risorse esterne' nel render della card IOC."""
import pytest
from fastapi.testclient import TestClient
from app import storage
from app.main import app
from app.models import Entity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "catalog.db")
    storage.init_db()


@pytest.fixture
def client(temp_db):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_ipv4_shows_catalog_resources(client):
    """v0.6.3: le risorse esterne non hanno più una sezione/intestazione a
    parte ('Risorse esterne') — sono fonti numerate #N nella stessa sequenza
    di estrattore/geo/RDAP/reputation."""
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert "AbuseIPDB" in r.text
    assert "https://www.abuseipdb.com/check/8.8.8.8" in r.text
    assert "source-rank" in r.text


def test_uncovered_type_has_no_catalog_section(client):
    # vat_id (Partita IVA) non ha risorse nel catalogo: solo la fonte #1
    # (estrattore). tax_id non è più adatto qui — ora mappa a site-cf.
    oid = storage.save_observation("y", [Entity("vat_id", "12345678903")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert '<span class="source-rank">#2</span>' not in r.text


def test_private_ipv4_shows_subnet_info_not_catalog(client):
    """Fix 3: per un IP privato/bogon il catalogo OSINT esterno (AbuseIPDB/BGP.HE.net)
    non ha senso — mostra invece info di rete locale (range RFC, classe storica)."""
    ent = Entity("ipv4", "192.168.1.1",
                 metadata={"extractor": "regex", "bogon": True, "bogon_type": "private"})
    oid = storage.save_observation("z", [ent])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    # "AbuseIPDB" compare anche nella status bar (ogni pagina) come nome del
    # pallino di stato: il controllo va scoping al contenuto principale,
    # non a "AbuseIPDB" ovunque nella pagina.
    content = r.text[r.text.index("<main"):]
    assert "AbuseIPDB" not in content
    assert "Rete privata" in content
    assert "RFC 1918" in content
    assert "Classe C" in content


# ── Task D: crt.sh/NVD diventano bottoni live-lookup on-demand (no API key) ──

def test_domain_shows_crtsh_live_lookup_button(client):
    oid = storage.save_observation("x", [Entity("domain", "example.com")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert "data-auto-lookup" in r.text
    assert f"/e/{oid}/lookup/site-crtsh/example.com" in r.text
    assert "crt.sh" in r.text


def test_cve_shows_nvd_live_lookup_button(client):
    oid = storage.save_observation("y", [Entity("cve", "CVE-2024-3400")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert "data-auto-lookup" in r.text
    assert f"/e/{oid}/lookup/site-nvd-nist/CVE-2024-3400" in r.text
    assert "NVD" in r.text


# ── Task F: urlscan.io (domain+url) e Team Cymru (ipv4) diventano bottoni
# live-lookup on-demand, stesso pattern di Task D (no API key) ──────────────

def test_domain_shows_both_crtsh_and_urlscan_buttons(client):
    """Un dominio ha 2 lookup live disponibili: crt.sh e urlscan.io insieme."""
    oid = storage.save_observation("x", [Entity("domain", "example.com")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-crtsh/example.com" in r.text
    assert f"/e/{oid}/lookup/site-urlscan-domain/example.com" in r.text
    assert "urlscan.io" in r.text


def test_url_shows_urlscan_live_lookup_button(client):
    oid = storage.save_observation("x", [Entity("url", "https://example.com/path")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert "data-auto-lookup" in r.text
    assert f"/e/{oid}/lookup/site-urlscan-url/" in r.text
    assert "urlscan.io" in r.text
    # VirusTotal è integrata (vedi test_url_shows_virustotal_live_lookup_when_key_configured),
    # ma qui VIRUSTOTAL_API_KEY non è configurata (autouse _clear_api_keys in
    # conftest.py) quindi resta link esterno.
    assert 'target="_blank"' in r.text
    assert "VirusTotal" in r.text


def test_url_shows_virustotal_live_lookup_when_key_configured(client, monkeypatch):
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "test-key-123")
    oid = storage.save_observation("x", [Entity("url", "https://example.com/path")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-virustotal-search/" in r.text
    assert "data-auto-lookup" in r.text


def test_public_ipv4_shows_virustotal_live_lookup_when_key_configured(client, monkeypatch):
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "test-key-123")
    oid = storage.save_observation("x", [Entity("ipv4", "93.184.216.34")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-virustotal-search/93.184.216.34" in r.text


def test_domain_shows_virustotal_live_lookup_when_key_configured(client, monkeypatch):
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "test-key-123")
    oid = storage.save_observation("x", [Entity("domain", "malware-drop-example.top")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-virustotal-search/malware-drop-example.top" in r.text


def test_public_ipv4_shows_shodan_live_lookup_keyless(client, monkeypatch):
    """Shodan è keyless: la scheda IOC mostra il lookup live (InternetDB
    gratuito) anche SENZA SHODAN_API_KEY. Con la key funziona uguale
    (in più prova l'host endpoint più ricco)."""
    monkeypatch.delenv("SHODAN_API_KEY", raising=False)
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-shodan/8.8.8.8" in r.text  # live, nessuna key

    monkeypatch.setenv("SHODAN_API_KEY", "test-key-123")
    oid2 = storage.save_observation("y", [Entity("ipv4", "8.8.4.4")])
    r2 = client.get(f"/e/{oid2}")
    assert r2.status_code == 200
    assert f"/e/{oid2}/lookup/site-shodan/8.8.4.4" in r2.text


def test_public_ipv4_shows_cymru_asn_live_lookup_button(client, monkeypatch):
    # ABUSEIPDB_API_KEY esplicitamente assente: indipendente da un eventuale
    # .env reale sulla macchina di sviluppo (load_dotenv() lo leggerebbe).
    monkeypatch.delenv("ABUSEIPDB_API_KEY", raising=False)
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-bgp-he-net/8.8.8.8" in r.text
    # AbuseIPDB resta link esterno senza API key configurata
    assert "https://www.abuseipdb.com/check/8.8.8.8" in r.text


def test_public_ipv4_shows_abuseipdb_live_lookup_when_key_configured(client, monkeypatch):
    """Ovviamente: se ABUSEIPDB_API_KEY è configurata, AbuseIPDB diventa un
    lookup live come crt.sh/urlscan.io/NVD/Cymru — non più un link esterno."""
    monkeypatch.setenv("ABUSEIPDB_API_KEY", "test-key-123")
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-abuseipdb/8.8.8.8" in r.text
    assert "data-auto-lookup" in r.text


# ── Persone + tool estesi (keyless, categoria Identità) ──────────────────────

def test_email_shows_gravatar_and_xposedornot_live_lookup(client):
    oid = storage.save_observation("x", [Entity("email", "mario.rossi@example.com")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-gravatar/mario.rossi%40example.com" in r.text
    assert f"/e/{oid}/lookup/site-xposedornot/mario.rossi%40example.com" in r.text
    assert "Identit" in r.text  # categoria Identità presente


def test_phone_shows_local_phone_info_live_lookup(client):
    oid = storage.save_observation("x", [Entity("phone", "+393331234567")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-phone-info/" in r.text


def test_public_ipv4_shows_urlscan_ip_live_lookup(client):
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-urlscan-ip/8.8.8.8" in r.text


# ── Threat-intel a key gratuita: live solo con la key configurata ────────────

def test_ipv4_shows_threatfox_and_otx_live_when_keyed(client, monkeypatch):
    monkeypatch.setenv("ABUSECH_API_KEY", "k")
    monkeypatch.setenv("OTX_API_KEY", "k")
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-threatfox/8.8.8.8" in r.text
    assert f"/e/{oid}/lookup/site-otx/8.8.8.8" in r.text


def test_ipv4_threatfox_stays_link_without_key(client, monkeypatch):
    monkeypatch.delenv("ABUSECH_API_KEY", raising=False)
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-threatfox/" not in r.text  # niente lookup live senza key


def test_email_shows_hunter_live_when_keyed(client, monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "k")
    oid = storage.save_observation("x", [Entity("email", "mario@example.com")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-hunter-verify/mario%40example.com" in r.text


# ── Dork keyless (locale) e Codice Fiscale: devono comparire come lookup live ─

def test_email_shows_dork_live(client):
    # I Google Dork sono keyless (auto-run locale): compaiono sempre per un'email.
    oid = storage.save_observation("x", [Entity("email", "mario@example.com")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-dorks-email/mario%40example.com" in r.text


def test_ipv4_shows_dork_live(client):
    oid = storage.save_observation("x", [Entity("ipv4", "8.8.8.8")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-dorks-ipv4/8.8.8.8" in r.text


def test_tax_id_shows_cf_decoder_live(client):
    oid = storage.save_observation("x", [Entity("tax_id", "BNCGLI85M41H501Y")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-cf/BNCGLI85M41H501Y" in r.text


# ── Batch persone Wave A: fonti live keyless auto-run (Identità) ─────────────

def test_email_shows_emailrep_live(client):
    oid = storage.save_observation("x", [Entity("email", "mario@example.com")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-emailrep/mario%40example.com" in r.text


def test_email_shows_hudsonrock_live(client):
    oid = storage.save_observation("x", [Entity("email", "mario@example.com")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-hudsonrock-email/mario%40example.com" in r.text


def test_username_shows_hudsonrock_live(client):
    oid = storage.save_observation("x", [Entity("username", "giuliab")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-hudsonrock-username/giuliab" in r.text


def test_username_shows_github_api_live(client):
    oid = storage.save_observation("x", [Entity("username", "octocat")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-github-api/octocat" in r.text


def test_username_shows_keybase_api_live(client):
    oid = storage.save_observation("x", [Entity("username", "chris")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-keybase-api/chris" in r.text


def test_username_shows_gitlab_api_live(client):
    oid = storage.save_observation("x", [Entity("username", "jane")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-gitlab-api/jane" in r.text


def test_username_shows_reddit_api_live(client):
    oid = storage.save_observation("x", [Entity("username", "spez")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-reddit-api/spez" in r.text


# ── Batch persone Wave B: fonti live key-gated (Identità, solo con key) ──────

def test_email_shows_ipqs_live_when_keyed(client, monkeypatch):
    monkeypatch.setenv("IPQS_API_KEY", "k")
    oid = storage.save_observation("x", [Entity("email", "mario@example.com")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-ipqs-email/mario%40example.com" in r.text


def test_phone_shows_ipqs_live_when_keyed(client, monkeypatch):
    monkeypatch.setenv("IPQS_API_KEY", "k")
    oid = storage.save_observation("x", [Entity("phone", "+393512345678")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-ipqs-phone/" in r.text


def test_phone_shows_numverify_live_when_keyed(client, monkeypatch):
    monkeypatch.setenv("NUMVERIFY_API_KEY", "k")
    oid = storage.save_observation("x", [Entity("phone", "+393512345678")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-numverify/" in r.text


def test_phone_numverify_stays_hidden_without_key(client, monkeypatch):
    monkeypatch.delenv("NUMVERIFY_API_KEY", raising=False)
    oid = storage.save_observation("x", [Entity("phone", "+393512345678")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-numverify/" not in r.text


# ── Batch persone Wave C1: infrastruttura on-demand (WhatsMyName) ───────────

def test_username_shows_whatsmyname_on_demand_not_auto(client):
    """WhatsMyName deve comparire ma SENZA data-auto-lookup: è on-demand,
    non deve partire da solo (a differenza di tutte le altre fonti Identità)."""
    oid = storage.save_observation("x", [Entity("username", "octocat")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-whatsmyname/octocat" in r.text
    assert "Ricerca approfondita" in r.text
    assert "btn-manual-lookup" in r.text
    idx = r.text.index("site-whatsmyname/octocat")
    window = r.text[max(0, idx - 400):idx]
    assert "data-auto-lookup" not in window


def test_email_shows_holehe_on_demand_not_auto(client):
    """Holehe deve comparire ma SENZA data-auto-lookup (on-demand)."""
    oid = storage.save_observation("x", [Entity("email", "mario@example.com")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-holehe/mario%40example.com" in r.text
    assert "Ricerca approfondita" in r.text
    idx = r.text.index("site-holehe/mario%40example.com")
    window = r.text[max(0, idx - 400):idx]
    assert "data-auto-lookup" not in window


def test_username_whatsmyname_still_under_renamed_category(client):
    """La rinomina della categoria (Task 4) non deve rompere WhatsMyName
    (Wave C1) — regressione mirata sulla stessa categoria condivisa."""
    oid = storage.save_observation("x", [Entity("username", "octocat")])
    r = client.get(f"/e/{oid}")
    assert r.status_code == 200
    assert f"/e/{oid}/lookup/site-whatsmyname/octocat" in r.text
    assert "Ricerca approfondita" in r.text
