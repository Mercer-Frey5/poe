"""env_writer.py — aggiorna .env in-place preservando commenti/ordine.

Usato dal pannello "API" nella status bar: l'Operatore incolla una key da UI
invece di editare .env a mano. Aggiorna SOLO le righe KEY=... richieste,
lascia tutto il resto (commenti, altre chiavi, righe vuote) intatto."""
from __future__ import annotations

from pathlib import Path

__all__ = ["write_env_keys"]


def write_env_keys(env_path: Path, updates: dict[str, str]) -> None:
    """Sostituisce le righe KEY=... esistenti in env_path (mantenendo
    posizione e il resto del file), aggiunge in fondo le chiavi assenti.
    Crea il file se non esiste già."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(updates)
    out_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        matched_key = next((k for k in remaining if stripped.startswith(f"{k}=")), None)
        if matched_key:
            out_lines.append(f"{matched_key}={remaining.pop(matched_key)}")
        else:
            out_lines.append(line)
    for key, value in remaining.items():
        out_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
