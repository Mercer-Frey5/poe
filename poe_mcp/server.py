"""FastMCP stdio server per POE-OSINT. Registra SOLO i tool ammessi dalla policy
in permissions.py (LOCAL sempre; LIVE_KEYLESS se POE_MCP_LIVE). Nessuna logica di
dominio qui: gli adapter delegano a service.py.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from poe_mcp import permissions, service


def build_server(live: bool | None = None) -> FastMCP:
    """Costruisce il server FastMCP registrando gli adapter dei soli tool abilitati.
    `live` forza il tier LIVE_KEYLESS (default: valore di POE_MCP_LIVE)."""
    if live is None:
        live = permissions.live_enabled()
    mcp = FastMCP("poe-osint")

    async def poe_analyze_text(text: str) -> dict:
        """Estrae entità (email, telefoni, IP, domini, hash, codici fiscali, ...) da
        testo libero in modo DETERMINISTICO (regex + spaCy). Nessun LLM, nessun
        salvataggio, nessuna rete. Input max 50k caratteri."""
        return service.analyze_text(text)

    async def poe_codice_fiscale_decode(cf: str) -> dict:
        """Decodifica un Codice Fiscale italiano (offline): sesso, data di nascita,
        comune, validità del carattere di controllo. Nessuna rete."""
        return await service.codice_fiscale(cf)

    async def poe_phone_info(phone: str) -> dict:
        """Metadati di un numero di telefono (offline, libreria phonenumbers):
        validità, regione, operatore, tipo linea, prefisso. Serve il prefisso
        internazionale (es. +39)."""
        return await service.phone_info(phone)

    async def poe_dorks_build(value: str, kind: str = "email") -> dict:
        """Costruisce Google dork mirati per un IOC (email/person_name/username/
        domain/ipv4/...). Solo stringhe e URL: NON interroga Google, nessuna rete."""
        return await service.dorks(value, kind)

    def poe_catalog_resources(entity_type: str | None = None) -> dict:
        """Elenca il catalogo di risorse OSINT di POE (dati di riferimento). Con
        entity_type filtra le risorse applicabili a quel tipo di IOC."""
        return service.catalog_resources(entity_type)

    def poe_reputation_lookup(value: str) -> dict:
        """Reputation locale di un IOC contro i feed pubblici (abuse.ch/blocklist)
        salvati in reputation.db. Nessuna rete."""
        return service.reputation_lookup(value)

    def poe_status() -> dict:
        """Stato del connettore MCP: versione, trasporto, tier abilitati e lista dei
        tool esposti. Nessuna PII. Ideale come smoke test dell'handshake."""
        return service.status()

    async def poe_crtsh_lookup(domain: str) -> dict:
        """[LIVE_KEYLESS] Certificate Transparency (crt.sh) di un dominio: numero di
        certificati, sottodomini, ultimo issuer. Trasmette SOLO il dominio
        interrogato, idempotente, nessuna quota. Attivo solo con POE_MCP_LIVE=1."""
        return await service.crtsh(domain)

    adapters = {
        "poe_analyze_text": poe_analyze_text,
        "poe_codice_fiscale_decode": poe_codice_fiscale_decode,
        "poe_phone_info": poe_phone_info,
        "poe_dorks_build": poe_dorks_build,
        "poe_catalog_resources": poe_catalog_resources,
        "poe_reputation_lookup": poe_reputation_lookup,
        "poe_status": poe_status,
        "poe_crtsh_lookup": poe_crtsh_lookup,
    }

    for name in permissions.default_enabled_tool_names(live=live):
        fn = adapters.get(name)
        if fn is None:  # difesa: policy e adapter devono restare allineati
            raise RuntimeError(f"tool ammesso in policy ma senza adapter: {name}")
        mcp.add_tool(fn, name=name)
    return mcp
