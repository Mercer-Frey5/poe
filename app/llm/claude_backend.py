"""claude_backend.py — backend LLM che usa Claude tramite la CLI **Claude Code**
in modalità headless (`claude -p`), quindi con il tuo **abbonamento** (Pro/Max),
NON con l'API a token (`ANTHROPIC_API_KEY`).

Perché Claude Code e non l'SDK API: l'API è metered/a pagamento e separata
dall'abbonamento; Claude Code usa la sessione già autenticata (l'abbonamento).
POE lancia `claude -p` come subprocess in una cwd neutra (niente contesto
progetto/CLAUDE.md) e parsa la risposta.

Attivazione: `POE_LLM_BACKEND=claude`. Modello opzionale: `POE_CLAUDE_MODEL`
(vuoto = default del piano). Binario override: `POE_CLAUDE_BIN`. Argomenti extra:
`POE_CLAUDE_EXTRA_ARGS` (spazio-separati, es. per disabilitare i tool se serve).

NB privacy: usare questo backend fa uscire i dati OSINT (IOC/PII) verso il cloud
Anthropic — è opt-in, il default resta il modello locale (MLX).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import tempfile

from app.llm.base import LLMBackend

logger = logging.getLogger(__name__)


class ClaudeCodeBackend(LLMBackend):
    def __init__(self, model: str = "", timeout: float = 240.0, binary: str = "claude") -> None:
        self._model = model or os.environ.get("POE_CLAUDE_MODEL", "")
        self._timeout = timeout
        self._bin = os.environ.get("POE_CLAUDE_BIN", binary)
        self._extra = shlex.split(os.environ.get("POE_CLAUDE_EXTRA_ARGS", ""))

    @property
    def model_name(self) -> str:
        return f"claude-code:{self._model or 'default'}"

    # ── costruzione comando + parsing (puri, testabili senza subprocess) ─────────
    def _build_cmd(self, prompt: str, system: str) -> list[str]:
        """`claude -p` in print-mode, output JSON (robusto). LEAN:
        --strict-mcp-config (senza --mcp-config -> zero MCP) + --tools "" (zero tool
        built-in). Senza, ogni chiamata carica le definizioni di TUTTI gli MCP/tool
        di Claude Code (~72k token/chiamata, misurato); lean scende a ~12k (~6x meno
        costo/limiti abbonamento, ~2x più veloce). NON usiamo --bare: forzerebbe
        ANTHROPIC_API_KEY (API a pagamento), mentre noi vogliamo l'abbonamento."""
        cmd = [self._bin, "-p", "--output-format", "json",
               "--strict-mcp-config", "--tools", ""]
        if self._model:
            cmd += ["--model", self._model]
        if system:
            cmd += ["--append-system-prompt", system]
        cmd += self._extra
        cmd.append(prompt)
        return cmd

    @staticmethod
    def _parse_output(stdout: str) -> str:
        """Estrae il testo di risposta. `claude -p --output-format json` ritorna un
        oggetto con il campo `result`. Fallback al testo grezzo se non è JSON."""
        stdout = (stdout or "").strip()
        if not stdout:
            return ""
        try:
            data = json.loads(stdout)
        except (ValueError, TypeError):
            return stdout
        if isinstance(data, dict):
            return (data.get("result") or data.get("text") or "").strip() or stdout
        return stdout

    # ── LLMBackend API ───────────────────────────────────────────────────────────
    @staticmethod
    def _subscription_env() -> dict:
        """Env SENZA ANTHROPIC_API_KEY/AUTH_TOKEN: forza Claude Code a usare
        l'ABBONAMENTO (OAuth login), MAI l'API a token. Garantisce zero addebiti
        per-token anche se una key fosse presente nell'ambiente o nel .env di POE."""
        return {k: v for k, v in os.environ.items()
                if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}

    async def generate(self, prompt: str, system: str = "") -> str:
        cmd = self._build_cmd(prompt, system)
        # cwd neutra: evita che Claude Code ingerisca il CLAUDE.md/progetto di POE.
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=tempfile.gettempdir(), env=self._subscription_env(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Claude Code: timeout dopo {self._timeout:.0f}s")
        if proc.returncode != 0:
            msg = (err.decode(errors="replace") if err else "").strip()[:300]
            raise RuntimeError(f"Claude Code: uscita {proc.returncode} — {msg}")
        return self._parse_output(out.decode(errors="replace"))

    async def is_available(self) -> bool:
        """Verifica leggera: la CLI esiste e risponde a --version. NON valida l'auth
        (una generate fallita degrada nella route, come per gli altri backend)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._bin, "--version",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except Exception:
            return False
