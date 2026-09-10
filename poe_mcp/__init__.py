"""poe_mcp — connettore MCP locale (stdio) tra POE-OSINT e Claude.

PLUS additivo: espone a Claude (Code + Desktop) un insieme *vettato* di tool di
POE-OSINT via Model Context Protocol, senza toccare nulla dell'esistente e senza
bypassare il billing di Claude.

Modello di sicurezza: allowlist a tier (vedi `permissions.py`). In v1 girano solo
i tool LOCAL (offline, no side-effect) e, opt-in via env `POE_MCP_LIVE`, i
LIVE_KEYLESS (rete idempotente, no quota). GATED/FORBIDDEN mai in v1.

Design: docs/superpowers/specs/2026-07-22-poe-mcp-connector-design.md
"""

__version__ = "0.1.0"
