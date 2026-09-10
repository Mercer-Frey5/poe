"""Modello di permessi allowlist a tier per il connettore MCP di POE.

Ogni tool esposto (o esponibile) è classificato in un Tier. In v1 il server
registra SOLO i tool LOCAL (sempre) e, se `POE_MCP_LIVE` è attivo, i LIVE_KEYLESS.
GATED e FORBIDDEN sono dichiarati per documentazione e come test di non-regressione
del confine di sicurezza — non vengono mai registrati.
"""
from __future__ import annotations

import os
from enum import Enum


class Tier(str, Enum):
    LOCAL = "local"                # compute locale: no rete, no DB write, no segreti
    LIVE_KEYLESS = "live_keyless"  # rete idempotente, no quota, 1 IOC (opt-in env)
    GATED = "gated"                # richiede conferma human-in-the-loop (non in v1)
    FORBIDDEN = "forbidden"        # mai esposto via MCP


# name -> Tier. LOCAL/LIVE_KEYLESS = tool reali di v1. GATED/FORBIDDEN elencano
# superfici note da tenere fuori (i test verificano che restino non-registrate).
REGISTRY: dict[str, Tier] = {
    # --- LOCAL (default allowed) ---
    "poe_analyze_text": Tier.LOCAL,
    "poe_codice_fiscale_decode": Tier.LOCAL,
    "poe_phone_info": Tier.LOCAL,
    "poe_dorks_build": Tier.LOCAL,
    "poe_catalog_resources": Tier.LOCAL,
    "poe_reputation_lookup": Tier.LOCAL,
    "poe_status": Tier.LOCAL,
    # --- LIVE_KEYLESS (opt-in via POE_MCP_LIVE) ---
    "poe_crtsh_lookup": Tier.LIVE_KEYLESS,
    # --- GATED (dichiarati, NON registrati in v1) ---
    "poe_storage_read": Tier.GATED,       # read PII dal DB osservazioni
    "poe_vault_recall": Tier.GATED,       # read archivio note personali dell'hub (PII)
    "poe_keyed_lookup": Tier.GATED,       # lookup a chiave/quota
    "poe_holehe_lookup": Tier.GATED,      # broadcast pesante (~120 siti)
    "poe_write_observation": Tier.GATED,  # scrittura DB
    "poe_llm_synthesis": Tier.GATED,      # invocazione LLM locale
    # --- FORBIDDEN (mai) ---
    "admin_reset": Tier.FORBIDDEN,        # POST /admin/reset (wipe DB)
    "settings_keys": Tier.FORBIDDEN,      # segreti in chiaro / scrittura .env
    "delete_observation": Tier.FORBIDDEN, # DELETE distruttivo
    "reputation_refresh": Tier.FORBIDDEN, # riscrive reputation.db
    "voice_pipeline": Tier.FORBIDDEN,     # /ws/speak, /speak, /v1/chat (lock+MLX)
    "vault_consolidate": Tier.FORBIDDEN,  # muta l'archivio di note dell'hub
}

_LIVE_ENV = "POE_MCP_LIVE"
_TRUTHY = {"1", "true", "yes", "on"}


def live_enabled() -> bool:
    """True se il tier LIVE_KEYLESS è abilitato via env POE_MCP_LIVE."""
    return os.environ.get(_LIVE_ENV, "").strip().lower() in _TRUTHY


def tools_in_tier(tier: Tier) -> list[str]:
    return [name for name, t in REGISTRY.items() if t is tier]


def default_enabled_tool_names(live: bool | None = None) -> list[str]:
    """Nomi dei tool che il server registra. LOCAL sempre; LIVE_KEYLESS se `live`
    (default: valore di POE_MCP_LIVE). GATED/FORBIDDEN mai."""
    if live is None:
        live = live_enabled()
    names = tools_in_tier(Tier.LOCAL)
    if live:
        names = names + tools_in_tier(Tier.LIVE_KEYLESS)
    return names


def is_forbidden(name: str) -> bool:
    return REGISTRY.get(name) is Tier.FORBIDDEN
