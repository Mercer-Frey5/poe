"""`.env.example` deve restare allineato alle variabili che il codice legge.

Il file era rimasto fermo a "POE v0.1 non richiede variabili d'ambiente" mentre
l'applicazione ne leggeva 17: chi clonava il repo non aveva modo di sapere quali
chiavi esistessero. Questo test fa fallire la build se si aggiunge un
`os.getenv(...)` senza documentarlo."""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ENV_EXAMPLE = _ROOT / ".env.example"

_SOURCE_DIRS = ("app", "poe_mcp")

# Variabili lette dal codice ma volutamente NON documentate come impostabili.
_ESCLUSE = {
    # Iniettata da pytest, non e' configurazione.
    "PYTEST_CURRENT_TEST",
    # Volutamente da NON impostare: POE la rimuove dall'ambiente del subprocess
    # Claude per garantire zero addebiti per-token. Documentata a parole nel
    # file, non come riga KEY=.
    "ANTHROPIC_API_KEY",
}

_GETENV_RE = re.compile(r"os\.(?:getenv|environ\.get)\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']")
_ENVIRON_IDX_RE = re.compile(r"os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*\]")
# Accesso indiretto: `_LIVE_ENV = "POE_MCP_LIVE"` ... `os.environ.get(_LIVE_ENV)`.
# Si risolve la costante nello stesso file (permissions.py fa cosi').
_INDIRETTO_RE = re.compile(r"os\.(?:getenv|environ\.get)\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[,)]")


def _vars_lette_dal_codice() -> set[str]:
    found: set[str] = set()
    for d in _SOURCE_DIRS:
        for py in (_ROOT / d).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            found.update(_GETENV_RE.findall(text))
            found.update(_ENVIRON_IDX_RE.findall(text))
            for name in _INDIRETTO_RE.findall(text):
                const = re.search(
                    r"^%s\s*=\s*[\"']([A-Z][A-Z0-9_]*)[\"']" % re.escape(name),
                    text, re.M,
                )
                if const:
                    found.add(const.group(1))
    return found - _ESCLUSE


def _vars_documentate() -> set[str]:
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.M))


def test_env_example_esiste():
    assert _ENV_EXAMPLE.is_file(), "manca POE-OSINT/.env.example"


def test_ogni_variabile_letta_e_documentata():
    mancanti = sorted(_vars_lette_dal_codice() - _vars_documentate())
    assert not mancanti, (
        "variabili lette dal codice ma assenti in .env.example: "
        + ", ".join(mancanti)
    )


def test_nessuna_variabile_documentata_e_morta():
    """L'inverso: righe in .env.example che il codice non legge piu'."""
    morte = sorted(_vars_documentate() - _vars_lette_dal_codice())
    assert not morte, (
        "variabili documentate in .env.example ma non lette da nessuna parte: "
        + ", ".join(morte)
    )


def test_env_example_non_contiene_valori():
    """Deve essere un template: nessun segreto committato per sbaglio."""
    for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if m and m.group(2).strip():
            # Un default innocuo e' ammesso solo se non sembra un segreto.
            assert len(m.group(2).strip()) < 12, (
                f"{m.group(1)} ha un valore che sembra un segreto: rimuovilo"
            )
