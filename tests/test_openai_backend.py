"""Un motore per tutto cio' che parla il protocollo OpenAI.

POE aveva tre motori cablati: MLX (solo Apple Silicon), Ollama, e Claude via
abbonamento. Chi usa LM Studio, llama.cpp in modalita' server, vLLM, LocalAI,
OpenRouter, Groq o un endpoint aziendale interno non aveva alcuna via — pur
avendo, tutti, la stessa identica API.

Un solo backend li copre, perche' fra loro cambia l'indirizzo, non il protocollo.
E' anche il modo piu' onesto di dire "portalo dove vuoi": non serve che POE
conosca il tuo fornitore.

Due cose contano piu' delle altre, ed entrambe sono questioni di fiducia.

**La chiave non deve mai comparire.** Va in un header, mai in un log, mai in un
messaggio d'errore, mai nell'URL. POE tratta dati altrui: un log incollato per
chiedere aiuto non deve regalare una credenziale.

**Molti server locali non vogliono chiave affatto.** Se fosse obbligatoria, LM
Studio e llama.cpp resterebbero fuori — ed erano il motivo per cui questo
backend esiste.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from app.llm.openai_backend import OpenAICompatBackend

_URL = "http://localhost:1234/v1/chat/completions"


def _risposta(testo: str = "ecco l'analisi"):
    return httpx.Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": testo}}],
    })


# ── configurazione ──────────────────────────────────────────────────────────

def test_indirizzo_e_modello_configurabili():
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1", model="qwen3-8b")
    assert "qwen3-8b" in b.model_name


def test_la_barra_finale_non_raddoppia_il_path():
    """Chi incolla l'indirizzo dalla schermata di LM Studio spesso porta con se'
    la barra finale: non deve produrre `/v1//chat/completions`."""
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1/", model="m")
    assert b.endpoint == "http://localhost:1234/v1/chat/completions"


def test_legge_la_configurazione_dall_ambiente(monkeypatch):
    monkeypatch.setenv("POE_OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("POE_OPENAI_MODEL", "meta-llama/llama-3.1-8b-instruct")
    b = OpenAICompatBackend()
    assert b.endpoint.startswith("https://openrouter.ai/api/v1")
    assert "llama-3.1-8b" in b.model_name


# ── la chiave ───────────────────────────────────────────────────────────────

def test_la_chiave_viaggia_nell_header():
    b = OpenAICompatBackend(base_url="http://x/v1", model="m", api_key="segreto")
    assert b.headers()["Authorization"] == "Bearer segreto"


def test_senza_chiave_non_si_manda_un_header_vuoto():
    """Molti server locali rifiutano un Authorization malformato: meglio non
    mandarlo che mandarlo vuoto."""
    assert "Authorization" not in OpenAICompatBackend(base_url="http://x/v1",
                                                      model="m").headers()


@pytest.mark.asyncio
@respx.mock
async def test_la_chiave_non_finisce_nel_messaggio_d_errore():
    """POE tratta dati altrui: un log incollato per chiedere aiuto non deve
    regalare una credenziale."""
    respx.post(_URL).mock(return_value=httpx.Response(401, text="unauthorized"))
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1", model="m",
                            api_key="sk-super-segreta-12345")
    out = await b.generate("prompt")
    assert "sk-super-segreta-12345" not in out
    assert "sk-" not in out


@pytest.mark.asyncio
@respx.mock
async def test_la_chiave_non_finisce_nemmeno_in_un_errore_di_rete():
    respx.post(_URL).mock(side_effect=httpx.ConnectError("giu'"))
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1", model="m",
                            api_key="sk-super-segreta-12345")
    assert "sk-" not in await b.generate("prompt")


# ── generazione ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_genera():
    respx.post(_URL).mock(return_value=_risposta("Il dominio risulta pulito."))
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1", model="m")
    assert await b.generate("analizza") == "Il dominio risulta pulito."


@pytest.mark.asyncio
@respx.mock
async def test_il_system_prompt_arriva_come_ruolo_separato():
    route = respx.post(_URL).mock(return_value=_risposta())
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1", model="m")
    await b.generate("domanda", system="sei un analista")
    corpo = route.calls[0].request.read().decode()
    assert '"role": "system"' in corpo or '"role":"system"' in corpo


@pytest.mark.asyncio
@respx.mock
async def test_una_risposta_senza_scelte_non_esplode():
    """Alcuni server rispondono 200 con un corpo vuoto quando il modello non e'
    caricato: e' un caso frequente su LM Studio."""
    respx.post(_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1", model="m")
    assert isinstance(await b.generate("x"), str)


@pytest.mark.asyncio
@respx.mock
async def test_un_corpo_non_json_non_esplode():
    respx.post(_URL).mock(return_value=httpx.Response(200, text="<html>errore</html>"))
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1", model="m")
    assert isinstance(await b.generate("x"), str)


# ── disponibilita' e contratto comune ai backend ───────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_disponibile_se_il_server_risponde():
    respx.get("http://localhost:1234/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "m"}]}))
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1", model="m")
    assert await b.is_available() is True


@pytest.mark.asyncio
@respx.mock
async def test_non_disponibile_se_il_server_e_giu():
    respx.get("http://localhost:1234/v1/models").mock(
        side_effect=httpx.ConnectError("giu'"))
    b = OpenAICompatBackend(base_url="http://localhost:1234/v1", model="m")
    assert await b.is_available() is False


def test_rispetta_il_contratto_dei_backend():
    from app.llm.base import LLMBackend
    assert issubclass(OpenAICompatBackend, LLMBackend)


def test_unload_esiste_ed_e_innocuo():
    """Il server e' remoto: non c'e' nulla da scaricare, ma lo swap di backend
    chiama unload su chiunque ce l'abbia."""
    OpenAICompatBackend(base_url="http://x/v1", model="m").unload()
