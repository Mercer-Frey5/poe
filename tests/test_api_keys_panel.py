"""GET /settings/api — pagina "Servizi & API": elenco degli strumenti che
POE usa (descrizione + IOC di competenza) e le chiavi dei servizi a
pagamento. Il valore configurato è mostrato in chiaro (POE è locale
mono-utente: chi apre la pagina ha già accesso a .env sul filesystem).
POST /api/settings/keys scrive le chiavi e aggiorna os.environ subito."""
import pytest
from fastapi.testclient import TestClient
import app.main as main_module
from app.main import app


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "_ENV_PATH", tmp_path / ".env")


@pytest.fixture(autouse=True)
def _fake_site_reachability(monkeypatch):
    """_render_api_keys_panel pinga il sito pubblico di ogni chiave gestita
    (site_reachability, vera chiamata di rete) — mockato di default per non
    colpire abuseipdb.com/virustotal.com/shodan.io ad ogni test."""
    async def _fake(url):
        return "online"
    monkeypatch.setattr("app.main.site_reachability", _fake)


@pytest.fixture
def client(temp_env):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_page_lists_managed_keys_not_configured_by_default(client):
    r = client.get("/settings/api")
    assert r.status_code == 200
    assert "non configurata" in r.text
    assert "AbuseIPDB" in r.text
    assert "VirusTotal" in r.text
    assert "Shodan" in r.text
    assert "IPQualityScore" in r.text
    assert "Numverify" in r.text


def test_test_key_route_reports_valid_key_ipqs(client, monkeypatch):
    async def _fake_ok(api_key):
        return {"ok": True, "detail": "chiave valida"}
    monkeypatch.setattr("app.main.test_ipqs_key", _fake_ok)

    r = client.post("/api/settings/keys/test/IPQS_API_KEY", data={"IPQS_API_KEY": "k"})
    assert r.status_code == 200
    assert "api-key-test-ok" in r.text


def test_test_key_route_reports_valid_key_numverify(client, monkeypatch):
    async def _fake_ok(api_key):
        return {"ok": True, "detail": "chiave valida"}
    monkeypatch.setattr("app.main.test_numverify_key", _fake_ok)

    r = client.post("/api/settings/keys/test/NUMVERIFY_API_KEY", data={"NUMVERIFY_API_KEY": "k"})
    assert r.status_code == 200
    assert "api-key-test-ok" in r.text


def test_page_lists_keyless_tools_with_description_and_ioc(client):
    r = client.get("/settings/api")
    assert "crt.sh" in r.text
    assert "Certificate Transparency" in r.text
    assert "dominio" in r.text


def test_page_lists_managed_keys_with_description_and_ioc(client):
    r = client.get("/settings/api")
    assert "abuse-confidence-score" in r.text  # AbuseIPDB
    assert "70+ motori antivirus" in r.text    # VirusTotal
    assert "porte aperte" in r.text            # Shodan


def test_page_shows_real_key_value_when_configured(client, monkeypatch):
    monkeypatch.setenv("ABUSEIPDB_API_KEY", "super-secret-value-12345")
    r = client.get("/settings/api")
    assert "super-secret-value-12345" in r.text
    assert "configurata" in r.text


def test_page_shows_empty_input_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("SHODAN_API_KEY", raising=False)
    r = client.get("/settings/api")
    assert 'name="SHODAN_API_KEY" value=""' in r.text


def test_save_writes_env_and_updates_environ_immediately(client, monkeypatch, tmp_path):
    monkeypatch.delenv("ABUSEIPDB_API_KEY", raising=False)
    r = client.post("/api/settings/keys", data={"ABUSEIPDB_API_KEY": "new-real-key"})
    assert r.status_code == 200
    assert "configurata" in r.text
    assert "new-real-key" in r.text  # eco del valore appena salvato
    # scritta su disco
    assert "ABUSEIPDB_API_KEY=new-real-key" in (tmp_path / ".env").read_text(encoding="utf-8")
    # subito attiva, senza restart
    import os
    assert os.environ.get("ABUSEIPDB_API_KEY") == "new-real-key"


def test_save_empty_field_clears_the_key(client, monkeypatch, tmp_path):
    """Il form ora mostra sempre il valore reale corrente: un campo svuotato
    e inviato vuoto è un'azione deliberata dell'utente, quindi rimuove la
    chiave (non più "non toccare" come quando il valore non era mai mostrato)."""
    (tmp_path / ".env").write_text("ABUSEIPDB_API_KEY=already-set\n", encoding="utf-8")
    monkeypatch.setenv("ABUSEIPDB_API_KEY", "already-set")
    r = client.post("/api/settings/keys", data={"ABUSEIPDB_API_KEY": ""})
    assert r.status_code == 200
    assert "non configurata" in r.text
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "ABUSEIPDB_API_KEY=" in content
    assert "ABUSEIPDB_API_KEY=already-set" not in content
    import os
    assert not os.environ.get("ABUSEIPDB_API_KEY")


def test_save_only_touches_submitted_keys(client, monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("VIRUSTOTAL_API_KEY=untouched\n", encoding="utf-8")
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "untouched")
    client.post("/api/settings/keys", data={"ABUSEIPDB_API_KEY": "abc"})
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "VIRUSTOTAL_API_KEY=untouched" in content
    assert "ABUSEIPDB_API_KEY=abc" in content


def test_test_key_route_reports_valid_key(client, monkeypatch):
    async def _fake_ok(api_key):
        assert api_key == "typed-not-yet-saved"
        return {"ok": True, "detail": "chiave valida"}
    monkeypatch.setattr("app.main.test_abuseipdb_key", _fake_ok)

    r = client.post("/api/settings/keys/test/ABUSEIPDB_API_KEY",
                     data={"ABUSEIPDB_API_KEY": "typed-not-yet-saved"})
    assert r.status_code == 200
    assert "api-key-test-ok" in r.text
    assert "chiave valida" in r.text


def test_test_key_route_reports_invalid_key(client, monkeypatch):
    async def _fake_fail(api_key):
        return {"ok": False, "error": "chiave non valida"}
    monkeypatch.setattr("app.main.test_virustotal_key", _fake_fail)

    r = client.post("/api/settings/keys/test/VIRUSTOTAL_API_KEY",
                     data={"VIRUSTOTAL_API_KEY": "bad-key"})
    assert r.status_code == 200
    assert "api-key-test-fail" in r.text
    assert "chiave non valida" in r.text


def test_test_key_route_empty_field_shows_hint(client):
    r = client.post("/api/settings/keys/test/SHODAN_API_KEY", data={"SHODAN_API_KEY": ""})
    assert r.status_code == 200
    assert "inserisci una chiave" in r.text


def test_test_key_route_unknown_key_name_400(client):
    r = client.post("/api/settings/keys/test/NOT_A_MANAGED_KEY", data={})
    assert r.status_code == 400


def test_page_sorts_problem_services_first_and_shows_health_dot(client, monkeypatch):
    """Dai precedenza ai servizi in down/con problemi: nella pagina, la riga
    del servizio offline deve comparire PRIMA di quella online, con un
    pallino di stato visibile (stesso linguaggio della status bar)."""
    async def _fake(url):
        if "shodan" in url:
            return "offline"
        return "online"
    monkeypatch.setattr("app.main.site_reachability", _fake)

    r = client.get("/settings/api")
    assert r.status_code == 200
    # La status bar (base.html) mostra già "AbuseIPDB"/"Shodan" come nomi dei
    # dot — l'ordine da verificare è quello DENTRO il pannello, non nel resto
    # della pagina, quindi si cerca a partire dal suo contenitore.
    panel = r.text[r.text.index('id="api-keys-panel-body"'):]
    assert panel.index("Shodan") < panel.index("AbuseIPDB")
    assert '<span class="status-dot offline"' in panel
    assert '<span class="status-dot online"' in panel
