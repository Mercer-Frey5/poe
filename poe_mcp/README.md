# poe_mcp — Connettore MCP locale POE ↔ Claude

Server **MCP (Model Context Protocol) locale su stdio** che collega **Claude Code** e
**Claude Desktop** a **POE-OSINT**. È un **PLUS additivo**: non modifica nulla dell'esistente
e **non** bypassa il billing di Claude (collega Claude ai *tool/dati* di POE, non a come Claude
è pagato). Gira solo sul Mac dove vive POE — zero esposizione di rete.

Design di riferimento: [`docs/superpowers/specs/2026-07-22-poe-mcp-connector-design.md`](../../docs/superpowers/specs/2026-07-22-poe-mcp-connector-design.md).

---

## 1. Cosa espone (tool `poe_*`)

### Tier LOCAL — sempre attivi, 100% offline
| Tool | Cosa fa |
|---|---|
| `poe_analyze_text` | Estrazione entità DETERMINISTICA (email/telefoni/IP/domini/hash/CF…) da testo. No LLM, no DB, no rete. Max 50k caratteri. |
| `poe_codice_fiscale_decode` | Reverse di un Codice Fiscale italiano: sesso, data nascita, comune, validità. |
| `poe_phone_info` | Metadati numero di telefono (regione, operatore, tipo linea) via `phonenumbers`. |
| `poe_dorks_build` | Costruisce Google dork mirati per un IOC. Solo stringhe/URL, non interroga Google. |
| `poe_catalog_resources` | Legge il catalogo di risorse OSINT di POE (dati di riferimento). |
| `poe_reputation_lookup` | Reputation IOC locale contro feed pubblici (abuse.ch/blocklist) in reputation.db. |
| `poe_status` | Stato del connettore: versione, tier abilitati, tool esposti. Smoke test, no PII. |

### Tier LIVE_KEYLESS — opt-in via `POE_MCP_LIVE=1` (default OFF)
| Tool | Cosa fa |
|---|---|
| `poe_crtsh_lookup` | Certificate Transparency (crt.sh) di un dominio. Idempotente, no quota, trasmette solo il dominio. |

Fuori da v1 (vedi §5): read PII dal DB, archivio di note dell'hub, lookup a chiave/quota, broadcast (holehe/
whatsmyname), qualsiasi scrittura, invocazione LLM. Sono **GATED** (richiederanno conferma) o
**FORBIDDEN** (mai).

---

## 2. Setup — cosa devi fare

Prerequisito (già fatto nello scheletro): la dipendenza `mcp` è nel venv di POE-OSINT
(`cd POE-OSINT && uv add mcp`).

### Claude Code (CLI)
```bash
# `claude mcp add` NON ha --cwd: si fa il cd in un wrapper bash (garantisce che
# `poe_mcp` e `app` siano importabili). `exec` sostituisce bash con python (processo pulito).
claude mcp add poe -- bash -c 'cd /path/to/POE-OSINT && exec .venv/bin/python -m poe_mcp'

# Alternativa senza wrapper (i path dati di POE sono già assoluti, serve solo l'import):
# claude mcp add poe -e PYTHONPATH=/path/to/POE-OSINT \
#   -- /path/to/POE-OSINT/.venv/bin/python -m poe_mcp
```
Poi verifica: `claude mcp list` → deve comparire `poe`. In una sessione Claude Code i tool
compaiono come `poe_analyze_text`, `poe_status`, ecc.

### Claude Desktop
Modifica `~/Library/Application Support/Claude/claude_desktop_config.json`, blocco `mcpServers`:
```json
{
  "mcpServers": {
    "poe": {
      "command": "/path/to/POE-OSINT/.venv/bin/python",
      "args": ["-m", "poe_mcp"],
      "cwd": "/path/to/POE-OSINT"
    }
  }
}
```
Riavvia Claude Desktop → i tool `poe_*` appaiono nel menu degli strumenti (icona 🔌).

### Abilitare il tier di rete keyless (opzionale)
Aggiungi `"env": {"POE_MCP_LIVE": "1"}` al blocco del server (Desktop) o esporta
`POE_MCP_LIVE=1` prima di `claude mcp add` (Code). Compare in più `poe_crtsh_lookup`.

> **cwd obbligatorio = `POE-OSINT/`**: il server importa sia `poe_mcp` sia `app` (POE-OSINT);
> avviato da un'altra directory gli import falliscono.

---

## 3. Demo (senza Claude)

```bash
cd POE-OSINT
.venv/bin/python -m poe_mcp.demo
```
Invoca ogni tool LOCAL con input d'esempio e stampa **esattamente il JSON che Claude
riceverebbe**. Nessuna rete (salvo crt.sh se `POE_MCP_LIVE=1`). Serve anche da smoke test.

Verifica dell'handshake MCP reale su stdio (facoltativa):
```bash
cd POE-OSINT && .venv/bin/python - <<'PY'
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
    p = StdioServerParameters(command=".venv/bin/python", args=["-m","poe_mcp"], cwd=".")
    async with stdio_client(p) as (r,w):
        async with ClientSession(r,w) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])
            print((await s.call_tool("poe_phone_info", {"phone":"+390212345678"})).content[0].text)
asyncio.run(main())
PY
```

---

## 4. Test

```bash
cd POE-OSINT
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```
Copre i wrapper di `service.py` (offline, con recognizer stub) e la policy dei permessi
(`permissions.py`): che i tool LOCAL siano sempre abilitati, i LIVE_KEYLESS solo con il flag, e
che GATED/FORBIDDEN non vengano MAI registrati.

---

## 5. Limiti — cosa può e cosa NON può fare

**Può (v1):**
- Estrarre entità da testo, decodificare CF, analizzare numeri di telefono, generare dork,
  leggere il catalogo OSINT e la reputation locale, riportare il proprio stato.
- (Opt-in) una CT-lookup keyless su crt.sh.
- Tutto **locale/offline** salvo il tier live esplicitamente abilitato.

**NON può (v1) — per scelta di sicurezza:**
- ❌ Leggere osservazioni/PII dal DB `poe.db` (soggetti d'indagine).
- ❌ Leggere l'archivio di note personali dell'hub (profilo, conversazioni, diario, agenda).
- ❌ Lanciare lookup a pagamento/quota (VirusTotal, AbuseIPDB, Shodan, IPQS, Numverify, OTX, Hunter).
- ❌ Lanciare lookup broadcast (holehe ~120 siti, whatsmyname 719 siti).
- ❌ **Scrivere** qualsiasi cosa (nessun salvataggio, nessuna annotazione, nessun evento agenda).
- ❌ Invocare l'LLM locale di POE (synthesis / entity-ai / extract-ai).
- ❌ Toccare la pipeline vocale dell'hub (`/ws/speak`, `/speak`, `/v1/chat/completions`).
- ❌ Reset/cancellazione DB, gestione API key, riscrittura feed reputation.
- ❌ Girare fuori dal Mac dove vive POE (stdio locale, per design).

Queste capacità stanno nei tier **GATED** (arriveranno dietro conferma human-in-the-loop) e
**FORBIDDEN** (escluse per sempre). Vedi il modello a tier in `permissions.py`.

## 6. Espandere il connettore

Non modificare a mano senza contratto: usa l'agente dedicato **`poe-mcp-builder`**
(`.claude/agents/poe-mcp-builder.md`). Classifica ogni nuovo tool in un Tier, TDD-first, e
mantiene allineati `permissions.py` / `service.py` / `server.py`. Percorso di crescita
(v1→v4 + esclusi) nella §10 del design doc.
