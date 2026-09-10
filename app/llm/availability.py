"""availability.py — quali motori AI puo' usare *questa* macchina.

POE nasceva tarato su un Mac M1: il backend predefinito era MLX, scritto nel
codice, su qualunque hardware. Chi lo scaricava su Windows o Linux otteneva un
avviso, un ripiego silenzioso su Ollama, e — se Ollama non c'era — un errore
incomprensibile al primo clic su una funzione AI.

Il difetto non era il ripiego, che e' giusto: era che nessuno diceva cosa stesse
succedendo. Qui si guarda la macchina e si risponde a due domande separate.

**Cosa e' utilizzabile**, per scegliere un default invece di imporne uno fisso.
L'ordine di preferenza mette il locale prima del cloud: se un motore gira su
questa macchina i dati non escono, e la privacy vale piu' della comodita'.

**Perche' il resto non lo e'.** "MLX non disponibile" non aiuta nessuno;
"MLX richiede Apple Silicon, qui l'architettura e' x86_64" dice cosa fare. Il
motivo viaggia accanto al verdetto e arriva fino a `/api/status`, cosi' chi ha
appena scaricato il progetto capisce da solo cosa gli manca.

Nessuna sonda e' obbligatoria e nessuna solleva: un motore che non si riesce a
verificare risulta non disponibile. E se non ce n'e' nessuno, POE resta
pienamente utile — la pipeline di estrazione e' deterministica e non usa LLM.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import socket
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ["Disponibilita", "rileva", "backend_predefinito", "e_apple_silicon",
           "ollama_attivo", "openai_configurato", "claude_installato", "e_locale"]

# Ordine di preferenza: prima il locale nativo, poi il locale portabile, infine
# il cloud. Non e' una classifica di qualita' — e' che i primi due tengono i dati
# sulla macchina.
_ORDINE = ("mlx", "ollama", "openai", "claude")

_PERCHE_NO = {
    "mlx": "MLX richiede Apple Silicon (Mac M1 o successivi). "
           "Su altro hardware si usa Ollama.",
    "ollama": "Ollama non risponde su 127.0.0.1:11434. "
              "Installalo da ollama.com, poi `ollama serve` e "
              "`ollama pull qwen3.5:9b-q4_K_M`.",
    "openai": "Nessun server compatibile OpenAI configurato. "
              "Imposta POE_OPENAI_BASE_URL (es. http://localhost:1234/v1 per "
              "LM Studio) e POE_OPENAI_MODEL.",
    "claude": "Il binario `claude` non e' installato. "
              "Serve Claude Code, autenticato con il tuo abbonamento.",
}

_PORTA_OLLAMA = 11434


# ── sonde reali ─────────────────────────────────────────────────────────────

def e_apple_silicon() -> bool:
    """ARM *e* macOS. Un Mac Intel e un Raspberry Pi vanno esclusi entrambi, per
    ragioni diverse: guardare solo l'architettura sbaglierebbe su tutti e due."""
    try:
        return platform.system() == "Darwin" and platform.machine() == "arm64"
    except Exception:                                   # noqa: BLE001
        return False


def ollama_attivo(host: str = "127.0.0.1", porta: int = _PORTA_OLLAMA) -> bool:
    """Ollama e' un servizio, non una libreria: puo' essere installato e spento.
    Si guarda la porta, non il binario, perche' e' la porta che serve davvero."""
    try:
        with socket.create_connection((host, porta), timeout=0.5):
            return True
    except Exception:                                   # noqa: BLE001
        return False


def e_locale(url: str) -> bool:
    """L'indirizzo tiene i dati sulla macchina, o li manda su Internet?

    Il backend compatibile OpenAI puo' puntare a LM Studio sulla stessa
    macchina o a un servizio come OpenRouter dall'altra parte del mondo:
    stesso protocollo, privacy opposta. Senza questa distinzione un endpoint
    cloud configurato dall'utente veniva mostrato come "locale" — l'esatto
    contrario di quello che la status bar promette.

    In dubbio (URL vuoto o illeggibile) si risponde False: il default deve
    essere quello prudente (assumere che i dati escano), non quello comodo."""
    from urllib.parse import urlparse
    import ipaddress
    try:
        host = urlparse(url).hostname or ""
    except Exception:                                   # noqa: BLE001
        return False
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False       # un dominio (openrouter.ai, ...) non e' mai locale
    return ip.is_loopback or ip.is_private


def openai_configurato() -> bool:
    """Basta che sia configurato: verificare che risponda costerebbe una
    richiesta di rete a ogni avvio, e il server puo' essere remoto e lento.
    Se poi non risponde, `generate` lo dice con chiarezza."""
    try:
        return bool(os.environ.get("POE_OPENAI_BASE_URL", "").strip())
    except Exception:                                   # noqa: BLE001
        return False


def claude_installato() -> bool:
    """Presenza del binario. Non verifica l'autenticazione: quella si scopre solo
    alla prima chiamata, e sondarla qui costerebbe secondi a ogni avvio."""
    try:
        return shutil.which("claude") is not None
    except Exception:                                   # noqa: BLE001
        return False


# ── esito ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Disponibilita:
    stato: dict[str, bool]

    def usabile(self, backend: str) -> bool:
        return bool(self.stato.get(backend, False))

    def motivo(self, backend: str) -> str:
        """Perche' NON si puo' usare. Stringa vuota se si puo'."""
        if self.usabile(backend):
            return ""
        return _PERCHE_NO.get(backend, f"motore sconosciuto: {backend!r}")

    def pronti(self) -> list[str]:
        return [b for b in _ORDINE if self.usabile(b)]

    def as_dict(self) -> dict[str, dict]:
        """Forma per `/api/status` e per il pannello impostazioni."""
        return {b: {"usabile": self.usabile(b), "motivo": self.motivo(b)}
                for b in _ORDINE}


def _sonda(fn) -> bool:
    """Una sonda che esplode vale "non disponibile": gira all'avvio, su hardware
    sconosciuto, e non puo' impedire a POE di partire."""
    try:
        return bool(fn())
    except Exception:                                   # noqa: BLE001
        logger.debug("sonda motore fallita", exc_info=True)
        return False


def rileva(apple_silicon=e_apple_silicon, ollama_attivo=ollama_attivo,
           claude_installato=claude_installato,
           openai_configurato=openai_configurato) -> Disponibilita:
    """Guarda la macchina. Le sonde sono iniettabili: i test non toccano
    l'hardware vero ne' la rete."""
    return Disponibilita({
        "mlx": _sonda(apple_silicon),
        "ollama": _sonda(ollama_attivo),
        "openai": _sonda(openai_configurato),
        "claude": _sonda(claude_installato),
    })


def backend_predefinito(d: Disponibilita, preferito: str = "") -> str | None:
    """Quale motore usare. `None` se non ce n'e' nessuno.

    Una scelta esplicita dell'utente vince — ma solo se e' realizzabile: imporre
    MLX su un PC senza Apple Silicon non lo fa funzionare, e vale piu' un motore
    che parte di uno che rispetta la richiesta e fallisce. Quando la scelta non
    e' realizzabile si ripiega sull'ordine di preferenza, e non in silenzio: chi
    chiama ha `motivo()` per dire perche'.

    Nessun motore non e' un errore. La pipeline di estrazione e' deterministica:
    POE resta utilizzabile, senza le sole funzioni di analisi."""
    preferito = (preferito or "").strip().lower()
    if preferito and d.usabile(preferito):
        return preferito
    if preferito and preferito in _ORDINE:
        logger.info("motore %r richiesto ma non utilizzabile: %s",
                    preferito, d.motivo(preferito))
    pronti = d.pronti()
    return pronti[0] if pronti else None
