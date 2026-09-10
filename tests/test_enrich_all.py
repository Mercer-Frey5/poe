"""Task 5: enrich_all arricchisce IP (batch) e domini in parallelo, degradando."""
import pytest
from app.enrichers import EnricherRegistry
from app.models import Entity


class _FakeIP:
    async def enrich_batch(self, ips):
        return {"8.8.8.8": {"country": "United States", "isp": "Google LLC"}}
    def can_enrich(self, e): return False  # batch gestito a parte
    async def enrich(self, e): return e


class _FakeWHOIS:
    def can_enrich(self, e): return e.type == "domain"
    async def enrich(self, e):
        return Entity(type=e.type, value=e.value, original=e.original,
                      confidence=e.confidence, derived_from=e.derived_from,
                      metadata={**e.metadata, "registrar": "MarkMonitor Inc."})


@pytest.mark.asyncio
async def test_enrich_all_geo_and_whois():
    reg = EnricherRegistry([_FakeIP(), _FakeWHOIS()])
    ents = [Entity("ipv4", "8.8.8.8"), Entity("domain", "google.com")]
    out = await reg.enrich_all(ents)
    by_val = {e.value: e for e in out}
    assert by_val["8.8.8.8"].metadata.get("country") == "United States"
    assert by_val["google.com"].metadata.get("registrar") == "MarkMonitor Inc."


@pytest.mark.asyncio
async def test_enrich_all_degrades_on_enricher_error():
    class _Boom:
        def can_enrich(self, e): return True
        async def enrich(self, e): raise RuntimeError("net down")
    reg = EnricherRegistry([_Boom()])
    out = await reg.enrich_all([Entity("domain", "x.com")])  # non solleva
    assert out[0].value == "x.com"
