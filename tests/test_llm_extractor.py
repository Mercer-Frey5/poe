import json
import pytest
from app.extractors.llm_extractor import LLMExtractor
from app.llm.base import LLMBackend


class _MockBackend(LLMBackend):
    def __init__(self, response: str, available: bool = True):
        self._response = response
        self._available = available

    @property
    def model_name(self) -> str:
        return "mock"

    async def generate(self, prompt: str, system: str = "") -> str:
        return self._response

    async def is_available(self) -> bool:
        return self._available


@pytest.mark.asyncio
async def test_returns_empty_when_unavailable():
    extractor = LLMExtractor(_MockBackend("", available=False))
    assert await extractor.async_extract("qualsiasi testo") == []


@pytest.mark.asyncio
async def test_extracts_org_name():
    payload = json.dumps({"org_names": ["Acme Srl"], "addresses": []})
    extractor = LLMExtractor(_MockBackend(payload))
    entities = await extractor.async_extract("Acme Srl ha sede a Roma")
    assert any(e.type == "org_name" and e.value == "Acme Srl" for e in entities)


@pytest.mark.asyncio
async def test_extracts_address():
    payload = json.dumps({
        "org_names": [],
        "addresses": [{"full_address": "Via Roma 1, 00100 Roma", "city": "Roma", "country": "Italia"}]
    })
    extractor = LLMExtractor(_MockBackend(payload))
    entities = await extractor.async_extract("risiede in Via Roma 1")
    addr = [e for e in entities if e.type == "address"]
    assert len(addr) == 1
    assert addr[0].metadata["city"] == "Roma"


@pytest.mark.asyncio
async def test_handles_malformed_json():
    extractor = LLMExtractor(_MockBackend("NON SONO JSON {broken}"))
    assert await extractor.async_extract("testo") == []


@pytest.mark.asyncio
async def test_sync_extract_is_noop():
    extractor = LLMExtractor(_MockBackend(""))
    assert extractor.extract("qualsiasi testo") == []


@pytest.mark.asyncio
async def test_org_confidence_is_low():
    payload = json.dumps({"org_names": ["TestCorp"], "addresses": []})
    extractor = LLMExtractor(_MockBackend(payload))
    entities = await extractor.async_extract("TestCorp")
    org = next(e for e in entities if e.type == "org_name")
    assert org.confidence == "low"
    assert org.metadata.get("extractor") == "llm"
