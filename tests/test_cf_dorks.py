"""Test per i tool keyless locali: reverse del Codice Fiscale (offline) e
generatore di Google Dork per tipo di IOC (costruzione locale di query/URL,
nessuna rete). Copre anche il wiring nel catalogo (tax_id -> site-cf, ecc.)."""
import pytest

from app.live_lookup import codice_fiscale_lookup, dorks_lookup, _cf_check_char
from app import osint_catalog


# ── Codice Fiscale (reverse locale, offline) ────────────────────────────────

@pytest.mark.asyncio
async def test_cf_valid_decodes_and_checkdigit_ok():
    # CF costruito con check digit corretto: valido=True e decodifica coerente.
    body = "RSSMRA85M01H501"
    cf = body + _cf_check_char(body)
    r = await codice_fiscale_lookup(cf)
    assert r["ok"] is True
    assert r["valido"] is True
    assert r["sesso"] == "maschio"
    assert r["data_nascita"] == "01/08/1985"
    assert r["comune"] == "Roma"
    assert r["codice_catastale"] == "H501"


@pytest.mark.asyncio
async def test_cf_female_day_offset():
    # Le femmine hanno il giorno di nascita +40: 01 -> giorno 41 nel CF.
    body = "RSSMRA85M41H501"
    cf = body + _cf_check_char(body)
    r = await codice_fiscale_lookup(cf)
    assert r["sesso"] == "femmina"
    assert r["data_nascita"].startswith("01/")


@pytest.mark.asyncio
async def test_cf_wrong_checkdigit_still_decodes_but_invalid():
    # Check digit errato: decodifica comunque i campi ma valido=False
    # (anti-allucinazione: segnala l'incoerenza invece di far finta di nulla).
    r = await codice_fiscale_lookup("RSSMRA85M01H501A")
    assert r["ok"] is True
    assert r["valido"] is False
    assert r["comune"] == "Roma"


@pytest.mark.asyncio
async def test_cf_foreign_born_z_code():
    # Codice catastale che inizia con Z = nato all'estero.
    body = "RSSMRA85M01Z404"
    cf = body + _cf_check_char(body)
    r = await codice_fiscale_lookup(cf)
    assert r["ok"] is True
    assert "estero" in r["comune"].lower()


@pytest.mark.asyncio
async def test_cf_invalid_format_errors():
    r = await codice_fiscale_lookup("non-un-cf")
    assert r["ok"] is False
    assert "error" in r


@pytest.mark.asyncio
async def test_cf_empty_input_errors():
    r = await codice_fiscale_lookup("")
    assert r["ok"] is False


# ── Google Dork (costruzione locale) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_dorks_email_builds_google_urls():
    r = await dorks_lookup("mario.rossi@x.it", "email")
    assert r["ok"] is True
    assert len(r["dorks"]) >= 1
    first = r["dorks"][0]
    assert set(first) == {"label", "query", "url"}
    assert first["url"].startswith("https://www.google.com/search?q=")


@pytest.mark.asyncio
async def test_dorks_value_is_url_encoded_in_link():
    # Il valore deve arrivare url-encoded nell'URL (niente caratteri grezzi).
    r = await dorks_lookup("a b&c", "email")
    assert all("a b&c" not in d["url"] for d in r["dorks"])
    assert any("%20" in d["url"] or "%26" in d["url"] for d in r["dorks"])


@pytest.mark.asyncio
async def test_dorks_unknown_kind_falls_back_to_exact_mention():
    r = await dorks_lookup("qualcosa", "tipo_inesistente")
    assert r["ok"] is True
    assert len(r["dorks"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["email", "person_name", "username",
                                  "social_handle", "phone", "domain", "ipv4"])
async def test_dorks_all_wired_kinds_produce_dorks(kind):
    r = await dorks_lookup("valore", kind)
    assert r["ok"] is True
    assert len(r["dorks"]) >= 1


# ── Wiring nel catalogo OSINT ───────────────────────────────────────────────

def test_catalog_maps_tax_id_to_cf():
    ids = [r["id"] for r in osint_catalog.resources_for_type("tax_id")]
    assert "site-cf" in ids


@pytest.mark.parametrize("entity_type,resource_id", [
    ("email", "site-dorks-email"),
    ("person_name", "site-dorks-person"),
    ("username", "site-dorks-username"),
    ("social_handle", "site-dorks-social"),
    ("phone", "site-dorks-phone"),
    ("domain", "site-dorks-domain"),
    ("ipv4", "site-dorks-ipv4"),
])
def test_catalog_maps_each_type_to_its_dork(entity_type, resource_id):
    ids = [r["id"] for r in osint_catalog.resources_for_type(entity_type)]
    assert resource_id in ids
