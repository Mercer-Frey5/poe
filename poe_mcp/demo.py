"""DEMO locale del connettore MCP POE <-> Claude: `python -m poe_mcp.demo`.

Invoca ogni tool del tier LOCAL con input d'esempio e stampa il JSON che Claude
riceverebbe. Nessun Claude, nessuna rete (salvo crt.sh se POE_MCP_LIVE=1). Serve
come dimostrazione E come smoke test end-to-end dei wrapper di service.py.
"""
from __future__ import annotations

import asyncio
import json

from poe_mcp import permissions, service

_SAMPLE_TEXT = (
    "Scrivi a mario.rossi@example.com oppure chiama +39 02 1234567. "
    "Dominio sospetto: evil.example.com, IP 185.203.112.45."
)

# (nome tool, callable che ritorna il risultato)
_STEPS = [
    ("poe_status", lambda: service.status()),
    ("poe_analyze_text", lambda: service.analyze_text(_SAMPLE_TEXT)),
    ("poe_codice_fiscale_decode", lambda: asyncio.run(service.codice_fiscale("RSSMRA85T10A562S"))),
    ("poe_phone_info", lambda: asyncio.run(service.phone_info("+390212345678"))),
    ("poe_dorks_build", lambda: asyncio.run(service.dorks("mario.rossi@example.com", "email"))),
    ("poe_catalog_resources", lambda: service.catalog_resources("email")),
    ("poe_reputation_lookup", lambda: service.reputation_lookup("185.203.112.45")),
]


def _show(name: str, result) -> None:
    print(f"\n── {name} " + "─" * max(4, 40 - len(name)))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    print("=" * 60)
    print(" POE ↔ Claude · DEMO connettore MCP (tier LOCAL)")
    print("=" * 60)
    for name, call in _STEPS:
        try:
            _show(name, call())
        except Exception as exc:  # la demo non deve mai crashare
            _show(name, {"errore_demo": str(exc)})

    if permissions.live_enabled():
        try:
            _show("poe_crtsh_lookup [LIVE]", asyncio.run(service.crtsh("example.com")))
        except Exception as exc:
            _show("poe_crtsh_lookup [LIVE]", {"errore_demo": str(exc)})
    else:
        print("\n(tier LIVE_KEYLESS off — `export POE_MCP_LIVE=1` per provare crt.sh)")

    print("\n" + "=" * 60)
    print(" Fine demo. Questi sono esattamente i dati che Claude vedrebbe")
    print(" chiamando i tool MCP `poe_*` esposti dal server stdio.")
    print("=" * 60)


if __name__ == "__main__":
    main()
