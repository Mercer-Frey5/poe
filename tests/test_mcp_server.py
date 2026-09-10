"""TDD per il connettore MCP locale POE <-> Claude (poe_mcp/).

Copre il layer `service` (wrapper sottili su app.*, testabili senza stdio) e il
registro permessi/tier. Nessuna rete: i tool LOCAL sono offline; il tier
LIVE_KEYLESS (crt.sh) è testato solo per la classificazione, non colpito.
"""
import asyncio


from poe_mcp import permissions, service
from poe_mcp.server import build_server


# ── Recognizer stub (evita il modello spaCy nei test) ────────────────────────
class _StubRecognizer:
    def recognize(self, text: str):
        from app.models import Entity
        return [Entity(type="email", value="mario@example.com")]


# ── service.analyze_text (wrap /api/analyze, deterministico) ─────────────────
def test_analyze_text_ok():
    out = service.analyze_text("contatta mario@example.com", recognizer=_StubRecognizer())
    assert out["count"] == 1
    assert out["entities"][0]["type"] == "email"
    assert out["entities"][0]["value"] == "mario@example.com"


def test_analyze_text_empty_is_error():
    out = service.analyze_text("   ", recognizer=_StubRecognizer())
    assert out.get("error")
    assert out["count"] == 0
    assert out["entities"] == []


def test_analyze_text_too_long_is_error():
    out = service.analyze_text("x" * 50_001, recognizer=_StubRecognizer())
    assert out.get("error")
    assert out["count"] == 0


# ── service.codice_fiscale (offline) ─────────────────────────────────────────
def test_codice_fiscale_structure():
    out = asyncio.run(service.codice_fiscale("RSSMRA85T10A562S"))
    assert out["ok"] is True
    assert set(("sesso", "data_nascita", "comune", "valido")) <= set(out)


def test_codice_fiscale_invalid():
    out = asyncio.run(service.codice_fiscale("non-un-cf"))
    assert out["ok"] is False
    assert out.get("error")


# ── service.phone_info (offline, phonenumbers) ───────────────────────────────
def test_phone_info_ok():
    out = asyncio.run(service.phone_info("+390212345678"))
    assert out["ok"] is True
    assert out["country_code"] == "+39"


def test_phone_info_unparsable():
    out = asyncio.run(service.phone_info("pippo"))
    assert out["ok"] is False


# ── service.dorks (offline, solo stringhe/URL) ───────────────────────────────
def test_dorks_build():
    out = asyncio.run(service.dorks("mario@example.com", "email"))
    assert out["ok"] is True
    assert len(out["dorks"]) > 0
    assert out["dorks"][0]["url"].startswith("https://www.google.com/search")


# ── service.catalog_resources (lettura catalogo locale) ──────────────────────
def test_catalog_resources_all():
    out = service.catalog_resources()
    assert out["ok"] is True
    assert out["count"] > 0


def test_catalog_resources_by_type():
    out = service.catalog_resources("ipv4")
    assert out["ok"] is True
    assert isinstance(out["resources"], list)


# ── service.reputation_lookup (locale, feed pubblici) ────────────────────────
def test_reputation_lookup_shape():
    out = service.reputation_lookup("8.8.8.8")
    assert out["ok"] is True
    assert isinstance(out["hits"], list)


# ── service.status (smoke, nessuna PII) ──────────────────────────────────────
def test_status_shape():
    out = service.status()
    assert out["server"] == "poe-osint"
    assert isinstance(out["tools_enabled"], list)
    assert "live" in out


# ── permissions: tier + allowlist ────────────────────────────────────────────
def test_tiers_exist():
    for name in ("LOCAL", "LIVE_KEYLESS", "GATED", "FORBIDDEN"):
        assert hasattr(permissions.Tier, name)


def test_default_enabled_is_local_only():
    names = set(permissions.default_enabled_tool_names(live=False))
    assert "poe_analyze_text" in names
    assert "poe_status" in names
    assert "poe_crtsh_lookup" not in names  # tier live off di default


def test_live_flag_adds_keyless_tier():
    names = set(permissions.default_enabled_tool_names(live=True))
    assert "poe_crtsh_lookup" in names


def test_forbidden_never_enabled():
    assert permissions.is_forbidden("admin_reset") is True
    enabled = set(permissions.default_enabled_tool_names(live=True))
    for name, tier in permissions.REGISTRY.items():
        if tier is permissions.Tier.FORBIDDEN:
            assert name not in enabled


def test_gated_not_enabled_in_v1():
    enabled = set(permissions.default_enabled_tool_names(live=True))
    for name, tier in permissions.REGISTRY.items():
        if tier is permissions.Tier.GATED:
            assert name not in enabled


# ── server: la registrazione FastMCP rispetta la policy dei permessi ─────────
def test_build_server_registers_exactly_enabled_local():
    srv = build_server(live=False)
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert names == set(permissions.default_enabled_tool_names(live=False))


def test_build_server_live_includes_keyless():
    srv = build_server(live=True)
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert "poe_crtsh_lookup" in names
