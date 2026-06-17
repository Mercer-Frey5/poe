import pytest
from app.llm.base import LLMBackend


class _StubBackend(LLMBackend):
    @property
    def model_name(self) -> str:
        return "stub"

    async def generate(self, prompt: str, system: str = "") -> str:
        return f"response to: {prompt}"

    async def is_available(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_stub_backend_generate():
    backend = _StubBackend()
    result = await backend.generate("hello")
    assert "hello" in result


@pytest.mark.asyncio
async def test_stub_backend_available():
    assert await _StubBackend().is_available() is True


def test_model_name():
    assert _StubBackend().model_name == "stub"


from unittest.mock import AsyncMock, MagicMock, patch
from app.llm.ollama_backend import OllamaBackend


@pytest.mark.asyncio
async def test_ollama_generate_returns_text():
    backend = OllamaBackend(model="qwen2.5:9b")
    mock_response = MagicMock()
    mock_response.response = "risultato di test"
    with patch.object(backend._client, "generate", new=AsyncMock(return_value=mock_response)):
        result = await backend.generate("testo input", system="sei un analista")
    assert result == "risultato di test"


@pytest.mark.asyncio
async def test_ollama_is_available_true():
    backend = OllamaBackend()
    with patch.object(backend._client, "list", new=AsyncMock(return_value={})):
        assert await backend.is_available() is True


@pytest.mark.asyncio
async def test_ollama_is_available_false_on_error():
    backend = OllamaBackend()
    with patch.object(backend._client, "list", new=AsyncMock(side_effect=Exception("connrefused"))):
        assert await backend.is_available() is False


def test_ollama_model_name():
    assert OllamaBackend(model="qwen2.5:9b").model_name == "qwen2.5:9b"
