"""openai_backend.py — un motore per tutto cio' che parla il protocollo OpenAI.

POE aveva tre motori cablati: MLX (solo Apple Silicon), Ollama, e Claude via
abbonamento. Chi usa LM Studio, llama.cpp in modalita' server, vLLM, LocalAI,
OpenRouter, Groq o un endpoint aziendale interno non aveva alcuna via — pur
avendo, tutti, la stessa identica API.

Un solo backend li copre, perche' fra loro cambia l'indirizzo, non il protocollo.
E' anche il modo piu' onesto di dire "portalo dove vuoi": non serve che POE
conosca il tuo fornitore, e nessuno deve scrivere codice per aggiungerne uno.

Si configura con tre variabili, o dal pannello impostazioni:

    POE_OPENAI_BASE_URL   http://localhost:1234/v1        (LM Studio)
                          http://localhost:8080/v1        (llama.cpp server)
                          https://openrouter.ai/api/v1    (OpenRouter)
    POE_OPENAI_MODEL      il nome del modello, come lo chiama quel server
    POE_OPENAI_API_KEY    opzionale: molti server locali non la vogliono

## Le due regole che contano

**La chiave non compare mai.** Va in un header, e non finisce in un log, in un
messaggio d'errore o in un URL. POE tratta dati altrui e i suoi errori vengono
incollati per chiedere aiuto: un messaggio che si porta dietro una credenziale la
regala. Per questo `generate` non propaga mai il corpo grezzo di un errore HTTP.

**La chiave e' opzionale.** Se fosse obbligatoria, LM Studio e llama.cpp — cioe'
il motivo per cui questo backend esiste — resterebbero fuori. Senza chiave non si
manda un `Authorization` vuoto: molti server lo rifiutano come malformato, ed e'
peggio che non mandarlo affatto.
"""
from __future__ import annotations

import logging
import os

import httpx

from app.llm.base import LLMBackend

logger = logging.getLogger(__name__)

__all__ = ["OpenAICompatBackend"]

_TIMEOUT = float(os.environ.get("POE_OPENAI_TIMEOUT", "120"))
_DEFAULT_BASE = "http://localhost:1234/v1"      # LM Studio, il caso piu' comune


class OpenAICompatBackend(LLMBackend):
    def __init__(self, base_url: str = "", model: str = "",
                 api_key: str = "", timeout: float = _TIMEOUT) -> None:
        base = (base_url or os.environ.get("POE_OPENAI_BASE_URL", "")
                or _DEFAULT_BASE).strip()
        # Chi incolla l'indirizzo da una schermata se ne porta spesso dietro la
        # barra finale: senza questo si otterrebbe `/v1//chat/completions`.
        self.base_url = base.rstrip("/")
        self._model = (model or os.environ.get("POE_OPENAI_MODEL", "")
                       or "local-model").strip()
        self._api_key = (api_key or os.environ.get("POE_OPENAI_API_KEY", "")).strip()
        self._timeout = timeout

    # ── configurazione ───────────────────────────────────────────────────────

    @property
    def model_name(self) -> str:
        return f"openai-compat:{self._model}"

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def headers(self) -> dict[str, str]:
        """Header della richiesta. `Authorization` solo se c'e' davvero una
        chiave: un header vuoto viene rifiutato da molti server locali."""
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    # ── generazione ──────────────────────────────────────────────────────────

    async def generate(self, prompt: str, system: str = "") -> str:
        """Risposta del modello, o una stringa che spiega cosa non ha funzionato.

        Non solleva e non propaga MAI il corpo grezzo della risposta: il 401 di
        un servizio a chiave puo' contenere l'header rifiutato, e questi messaggi
        finiscono nei log e negli incolla per chiedere aiuto."""
        messaggi = []
        if system:
            messaggi.append({"role": "system", "content": system})
        messaggi.append({"role": "user", "content": prompt})

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(self.endpoint, headers=self.headers(),
                                      json={"model": self._model, "messages": messaggi})
        except Exception as exc:                        # noqa: BLE001
            # Solo il TIPO dell'eccezione: il testo puo' contenere l'URL, e
            # qualcuno potrebbe averci messo dentro le credenziali.
            logger.warning("openai-compat: %s non raggiungibile (%s)",
                           self.base_url, type(exc).__name__)
            return (f"Il server AI su {self.base_url} non risponde "
                    f"({type(exc).__name__}). Verifica che sia avviato.")

        if r.status_code != 200:
            logger.warning("openai-compat: HTTP %s da %s", r.status_code, self.base_url)
            return self._spiega(r.status_code)

        try:
            scelte = r.json().get("choices") or []
        except (ValueError, AttributeError):
            return (f"Il server su {self.base_url} ha risposto qualcosa che non e' "
                    "JSON: probabilmente non e' un endpoint compatibile OpenAI.")
        if not scelte:
            # Frequente su LM Studio quando nessun modello e' caricato.
            return (f"Il server su {self.base_url} ha risposto senza contenuto. "
                    "Di solito significa che non c'e' un modello caricato.")
        return str((scelte[0].get("message") or {}).get("content") or "").strip()

    def _spiega(self, status: int) -> str:
        """Cosa fare, per codice. Mai il corpo della risposta: potrebbe contenere
        la chiave appena rifiutata."""
        if status in (401, 403):
            return ("Il server AI ha rifiutato le credenziali. Controlla "
                    "POE_OPENAI_API_KEY, o toglila se quel server non la vuole.")
        if status == 404:
            return (f"Endpoint non trovato su {self.base_url}. L'indirizzo deve "
                    "finire con /v1 (es. http://localhost:1234/v1).")
        if status == 429:
            return "Il server AI ha imposto un limite di richieste: riprova fra poco."
        return f"Il server AI ha risposto con HTTP {status}."

    # ── disponibilita' ───────────────────────────────────────────────────────

    async def is_available(self) -> bool:
        """`/models` e' l'unico endpoint che tutti implementano e che non consuma
        nulla."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.base_url}/models", headers=self.headers())
            return r.status_code == 200
        except Exception:                               # noqa: BLE001
            return False

    def unload(self) -> None:
        """Il server e' un altro processo, spesso un'altra macchina: qui non c'e'
        nulla da liberare."""
        return None
