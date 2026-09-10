"""Task 3: IPEnricher batch endpoint ip-api."""
import pytest
from app.enrichers.ip_enricher import IPEnricher


def test_parse_batch_maps_query_to_metadata():
    data = [
        {"status": "success", "query": "8.8.8.8", "country": "United States",
         "city": "Mountain View", "isp": "Google LLC", "org": "Google",
         "lat": 37.4, "lon": -122.0},
        {"status": "fail", "query": "1.2.3.4", "message": "reserved range"},
    ]
    out = IPEnricher()._parse_batch(data)
    assert out["8.8.8.8"]["country"] == "United States"
    assert out["8.8.8.8"]["isp"] == "Google LLC"
    assert "1.2.3.4" not in out  # status fail scartato


@pytest.mark.asyncio
async def test_enrich_batch_skips_private_ips(monkeypatch):
    enr = IPEnricher()

    async def _fake_post(ips):
        assert "8.8.8.8" in ips and "192.168.1.1" not in ips
        return {"8.8.8.8": {"country": "United States"}}

    monkeypatch.setattr(enr, "_post_batch", _fake_post)
    out = await enr.enrich_batch(["8.8.8.8", "192.168.1.1"])
    assert out["8.8.8.8"]["country"] == "United States"
