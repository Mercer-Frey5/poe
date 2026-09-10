import pytest
from app.enrichers.social_enricher import disambiguate_platform


def test_linkedin_detected():
    assert disambiguate_platform("@mrossi", "linkedin.com/in/mrossi @mrossi") == "linkedin"


def test_twitter_detected():
    assert disambiguate_platform("@xyz", "twitter.com/xyz @xyz") == "twitter"


def test_instagram_detected():
    assert disambiguate_platform("@photo", "instagram.com/photo") == "instagram"


def test_telegram_detected():
    assert disambiguate_platform("@news", "t.me/news @news") == "telegram"


def test_unknown_when_no_clue():
    assert disambiguate_platform("@user", "Contatto: @user") == "unknown"

# ── Task 11: IPEnricher ────────────────────────────────────────────────────────
import respx
import httpx
from app.enrichers.ip_enricher import IPEnricher
from app.models import Entity


def _ip(val: str, bogon: bool = False) -> Entity:
    meta = {"bogon": True} if bogon else {}
    return Entity(type="ipv4", value=val, confidence="medium", metadata=meta)


def test_ip_can_enrich_public():
    assert IPEnricher().can_enrich(_ip("8.8.8.8")) is True


def test_ip_cannot_enrich_bogon():
    assert IPEnricher().can_enrich(_ip("192.168.1.1", bogon=True)) is False


@pytest.mark.asyncio
@respx.mock
async def test_ip_adds_geo_metadata():
    respx.get("http://ip-api.com/json/8.8.8.8").mock(return_value=httpx.Response(200, json={
        "status": "success", "country": "United States", "city": "Mountain View",
        "isp": "Google LLC", "org": "Google", "lat": 37.4, "lon": -122.0,
    }))
    enriched = await IPEnricher().enrich(_ip("8.8.8.8"))
    assert enriched.metadata["country"] == "United States"
    assert enriched.metadata["isp"] == "Google LLC"


@pytest.mark.asyncio
@respx.mock
async def test_ip_returns_original_on_failure():
    respx.get("http://ip-api.com/json/8.8.8.8").mock(return_value=httpx.Response(500))
    original = _ip("8.8.8.8")
    assert await IPEnricher().enrich(original) == original


# ── Task 12: WHOISEnricher ────────────────────────────────────────────────────
from unittest.mock import patch
from app.enrichers.whois_enricher import WHOISEnricher


def _domain(val: str) -> Entity:
    return Entity(type="domain", value=val, confidence="medium")


def test_whois_can_enrich_domain():
    assert WHOISEnricher().can_enrich(_domain("example.com")) is True


def test_whois_can_enrich_public_ip():
    # v0.5: WHOIS/RDAP copre anche gli IP pubblici (via RDAP).
    assert WHOISEnricher().can_enrich(Entity(type="ipv4", value="8.8.8.8")) is True


def test_whois_cannot_enrich_bogon_ip():
    # ...ma non gli IP non instradabili (bogon/private): niente RDAP pubblico.
    e = Entity(type="ipv4", value="192.168.1.1", metadata={"bogon": True})
    assert WHOISEnricher().can_enrich(e) is False


@pytest.mark.asyncio
async def test_whois_adds_registrar():
    # Domini = RDAP-only (niente più fallback python-whois porta-43): testiamo il path RDAP.
    from app.enrichers import whois_enricher as _we
    _we._CACHE.clear()

    async def _fake_rdap(domain):
        return {"registrar": "MarkMonitor Inc.", "creation_date": "1997-09-15",
                "expiration_date": None, "updated_date": None, "status": None,
                "dnssec": "unsigned", "name_servers": ["ns1.example.com"]}

    with patch("app.enrichers.whois_enricher._rdap_domain", new=_fake_rdap):
        enriched = await WHOISEnricher().enrich(_domain("example.com"))
    assert enriched.metadata["registrar"] == "MarkMonitor Inc."


@pytest.mark.asyncio
async def test_whois_returns_original_on_failure():
    # Sia RDAP sia python-whois falliscono → ritorna l'entità originale.
    from app.enrichers import whois_enricher as _we
    _we._CACHE.clear()
    with patch("app.enrichers.whois_enricher._rdap_domain", side_effect=Exception("no rdap")), \
         patch("whois.whois", side_effect=Exception("timeout")):
        original = _domain("example.com")
        assert await WHOISEnricher().enrich(original) == original


@pytest.mark.asyncio
async def test_whois_ip_adds_ripe_abuse_contact():
    """Idea da tool WHOIS legacy: stat.ripe.net/data/abuse-contact-finder,
    keyless, complementare a rdap_abuse (a volte vuoto in RDAP puro)."""
    from app.enrichers import whois_enricher as _we
    _we._CACHE.clear()

    async def _fake_rdap_ip(ip):
        return {"rdap_name": "GOOGLE", "rdap_country": "US", "rdap_cidr": "8.8.8.0/24",
                "rdap_org": None, "rdap_abuse": None}

    async def _fake_ripe(ip):
        return ["abuse@google.com", "security@google.com"]

    with patch("app.enrichers.whois_enricher._rdap_ip", new=_fake_rdap_ip), \
         patch("app.enrichers.whois_enricher._ripe_abuse_contact", new=_fake_ripe):
        enriched = await WHOISEnricher().enrich(Entity(type="ipv4", value="8.8.8.8"))
    assert enriched.metadata["ripe_abuse_contacts"] == "abuse@google.com, security@google.com"
    assert enriched.metadata["rdap_name"] == "GOOGLE"


@pytest.mark.asyncio
async def test_whois_ip_rdap_survives_ripe_failure():
    """Se RIPEstat fallisce, i dati RDAP (già ottenuti) non vanno persi."""
    from app.enrichers import whois_enricher as _we
    _we._CACHE.clear()

    async def _fake_rdap_ip(ip):
        return {"rdap_name": "GOOGLE", "rdap_country": "US", "rdap_cidr": None,
                "rdap_org": None, "rdap_abuse": None}

    async def _fake_ripe(ip):
        raise Exception("ripe down")

    with patch("app.enrichers.whois_enricher._rdap_ip", new=_fake_rdap_ip), \
         patch("app.enrichers.whois_enricher._ripe_abuse_contact", new=_fake_ripe):
        enriched = await WHOISEnricher().enrich(Entity(type="ipv4", value="8.8.8.8"))
    assert enriched.metadata["rdap_name"] == "GOOGLE"
    assert "ripe_abuse_contacts" not in enriched.metadata


# ── Task 13: EnricherRegistry ─────────────────────────────────────────────────
from app.enrichers import EnricherRegistry
from app.enrichers.base import BaseEnricher


class _TagEnricher(BaseEnricher):
    def can_enrich(self, entity: Entity) -> bool:
        return entity.type == "ipv4"

    async def enrich(self, entity: Entity) -> Entity:
        return Entity(
            type=entity.type, value=entity.value,
            metadata={**entity.metadata, "tagged": True},
        )


@pytest.mark.asyncio
async def test_registry_enriches_matching():
    registry = EnricherRegistry([_TagEnricher()])
    entities = [Entity(type="ipv4", value="1.2.3.4"), Entity(type="email", value="a@b.com")]
    result = await registry.enrich_on_demand("ipv4", "1.2.3.4", entities)
    ip = next(e for e in result if e.type == "ipv4")
    assert ip.metadata.get("tagged") is True


@pytest.mark.asyncio
async def test_registry_skips_non_matching():
    registry = EnricherRegistry([])
    entities = [Entity(type="ipv4", value="1.2.3.4")]
    result = await registry.enrich_on_demand("ipv4", "1.2.3.4", entities)
    assert not result[0].metadata.get("tagged")
