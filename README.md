# POE-OSINT — Entity Extraction Engine

Tool OSINT per l'estrazione **deterministica e verificabile** di entità da testo libero.
Threat-intelligence, cybersecurity e ricerca su persone. Locale, offline-first.

> **Il principio, e la sua conseguenza pratica.**
> L'estrazione è deterministica: regex più NER. **Nessun modello tocca mai le entità
> estratte** — non le inventa, non le corregge, non le riscrive. L'AI vive fuori dal
> percorso critico, ospite su richiesta esplicita, per la sola sintesi investigativa.
> Quindi: **senza alcun motore AI POE funziona lo stesso.** Si perdono sintesi e analisi,
> non l'estrazione. Non serve una GPU per iniziare.

**Stato:** v0.8.0 · 839 test verdi · Python 3.12–3.13 · macOS, Linux, Windows

---

## Cosa fa

Incolli un testo, POE estrae e classifica le entità riconosciute, ciascuna marcata con un
**livello di confidenza onesto** che riflette la natura della verifica, non il desiderio di
sembrare affidabili: `high` = verifica matematica (check digit, libreria validatrice),
`medium` = verifica formale (pattern, whitelist TLD), `low` = estrazione statistica (NER).

**16 tipi riconosciuti:** `email`, `phone` (normalizzato E.164), `url`, `domain`, `ipv4`,
`hash_md5`, `hash_sha256`, `cve`, `username`, `social_handle`, `person_name`, `org_name`,
`address`, `tax_id` (codice fiscale IT con check digit), `vat_id` (P.IVA IT con check digit),
`birth_date`.

**Pipeline di estrazione** — sincrona, zero rete, millisecondi e non secondi su testi tipici:

- **Regex** per i tipi a pattern forte, con verifica del check digit dove esiste
- **spaCy NER** (`it_core_news_lg` + `en_core_web_lg`) per nomi di persona e organizzazioni
- **Deobfuscatore** (`hxxp://`, `[.]`, `(at)`, `(dot)`) con ricostruzione della forma originale
- **Normalizzatori** — telefoni E.164 via `phonenumbers`, TLD su lista IANA

**Sopra la base deterministica:**

- **Correlazione e pivot** — indice di co-occorrenza fra osservazioni, badge `⇄ PIVOT N`
  sull'indicatore, vista degli IOC correlati
- **Reputation locale** — 5 feed (ThreatFox, URLhaus, Feodo, MalwareBazaar, blocklist.de)
  scaricati e aggiornati in un DB separato: il lookup al query-time è **100% locale, nessuna rete**
- **Risk scoring** — punteggio e verdetto per IOC da segnali già presenti, pesi in
  `app/config/risk_weights.yaml`
- **28 lookup on-demand** — 25 verso fonti esterne (crt.sh, urlscan, NVD, Team Cymru,
  AbuseIPDB, VirusTotal, Shodan, OTX, ThreatFox, URLhaus, Gravatar, XposedOrNot, Hudson Rock,
  GitHub/GitLab/Keybase/Reddit, Hunter.io, IPQualityScore, Numverify, EmailRep,
  WhatsMyName (719 siti), Holehe) e 3 calcolati **in locale, senza rete** (decodifica del
  codice fiscale, Google dork, dati del numero di telefono). Ognuno parte **solo** su
  richiesta esplicita
- **Catalogo OSINT** — 60 risorse (55 siti, 4 Google dork, 1 tool locale) proposte per tipo di IOC
- **Report investigativo** — export `.md` arricchito, `.json` machine-readable, PDF

---

## Avvio

Serve **Python 3.12 o 3.13**. I comandi qui sotto usano [`uv`](https://docs.astral.sh/uv/);
in fondo trovi l'equivalente con `pip`.

I due modelli spaCy pesano **circa 1 GB in tutto** (`it_core_news_lg` ~630 MB,
`en_core_web_lg` ~445 MB): è il download più lungo dell'installazione, e va fatto una volta.
Sono identici su ogni piattaforma — **l'estrazione è la stessa ovunque**. Fra un sistema e
l'altro cambia soltanto il motore d'analisi AI.

### macOS (Apple Silicon)

```bash
uv sync
uv run python -m spacy download it_core_news_lg
uv run python -m spacy download en_core_web_lg
./scripts/run.sh                 # → http://localhost:8000
```

`uv sync` installa anche MLX, il motore locale nativo di Apple Silicon (i pacchetti `mlx` e
`mlx-lm` sono dichiarati con marker `sys_platform == 'darwin'`).

### Linux e Windows

Identico, meno MLX — che non viene nemmeno installato, quindi `uv sync` non fallisce e non
scarica nulla di inutile. Il motore locale qui è **Ollama**:

```bash
uv sync
uv run python -m spacy download it_core_news_lg
uv run python -m spacy download en_core_web_lg

# motore AI locale (opzionale: senza, l'estrazione funziona lo stesso)
#   installa Ollama da ollama.com, poi:
ollama serve
ollama pull qwen3.5:9b-q4_K_M

uv run uvicorn app.main:app --port 8000        # → http://localhost:8000
```

`uvicorn` diretto lascia scegliere il motore a POE (vedi sotto). `./scripts/run.sh` funziona
anche qui, ma parte chiedendo MLX: fuori da Apple Silicon ripiega sul primo motore
utilizzabile e scrive nel log **perché**. Per evitare il giro: `./scripts/run.sh --ollama`.

### Docker (qualunque piattaforma)

```bash
mkdir -p data && chmod 777 data   # il container gira come utente non privilegiato (uid 1000)
docker compose up
```

L'immagine scarica i modelli spaCy da sé. Nel container il motore locale è Ollama, che gira
**sull'host**: `docker-compose.yml` lo raggiunge via `host.docker.internal:11434`. Il DB
resta su `./data` sul disco dell'host.

Il processo nel container **non gira come root** — né i volumi né le dipendenze richiedono
quel privilegio. Perciò `./data` deve essere scrivibile da uid 1000 **prima** del primo
avvio: `chmod 777 data` è la via rapida su una macchina personale,
`sudo chown -R 1000:1000 data` quella stretta. Se la cartella esiste già da una versione
precedente, quando il container girava come root, i permessi vanno corretti allo stesso
modo: altrimenti POE non riesce a scrivere il DB.

### Con pip, senza uv

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download it_core_news_lg
python -m spacy download en_core_web_lg
uvicorn app.main:app --port 8000
```

`requirements.txt` è allineato a `pyproject.toml` da un test. Non contiene MLX (solo macOS)
né `mcp`, che serve al solo connettore MCP: per quello usa `uv sync`.

---

## Il motore AI: lo sceglie la macchina

All'avvio POE guarda l'hardware e sceglie da sé, **preferendo il locale al cloud** — non è
una classifica di qualità, è che un motore locale non fa uscire i dati dalla macchina.

| Motore | Dove gira | Come si abilita |
|---|---|---|
| **MLX** | Solo Apple Silicon (Mac M1 o successivi) | incluso in `uv sync` su macOS |
| **Ollama** | Qualunque hardware | `ollama serve` su `127.0.0.1:11434` |
| **Compatibile OpenAI** | Ovunque parli quel protocollo | `POE_OPENAI_BASE_URL` + `POE_OPENAI_MODEL` |
| **Claude** | Cloud | binario `claude` installato e autenticato |

Il backend **compatibile OpenAI** è uno solo e li copre tutti, perché fra questi servizi
cambia l'indirizzo, non il protocollo: **LM Studio** (`http://localhost:1234/v1`),
**llama.cpp** in modalità server (`http://localhost:8080/v1`), **vLLM** e **LocalAI**
(`http://localhost:8000/v1`), **OpenRouter** (`https://openrouter.ai/api/v1`), o un endpoint
aziendale interno. La chiave è **opzionale**: molti server locali non la vogliono.

**Chi manda dati fuori non è "Claude", è "dove punti l'indirizzo".** Claude è sempre cloud —
opt-in esplicito, e POE rimuove `ANTHROPIC_API_KEY` dall'ambiente del subprocess per
garantire zero addebiti per token, visto che usa l'abbonamento e non l'API a consumo. Ma il
backend compatibile OpenAI può puntare a LM Studio sulla stessa macchina *o* a OpenRouter
dall'altra parte del mondo: stesso protocollo, privacy opposta. POE lo riconosce da solo —
localhost e rete privata (`192.168.x`, `10.x`, …) contano come locali, un dominio pubblico
no — e lo espone come `kind: "local"` o `kind: "cloud"` in `/api/status` e nella risposta di
`/admin/llm/backend`. Claude ha un valore proprio, `kind: "claude"`, ed è sempre cloud: per un
client l'unico valore che significa "i dati restano qui" è `local`. **Ogni volta che il motore
scelto all'avvio non è locale, POE lo scrive nei log**, non lo lascia scoprire aprendo
l'interfaccia dopo che un'analisi è già partita.

**Quando un motore non è disponibile, POE dice perché.** "MLX non disponibile" non aiuta
nessuno; "MLX richiede Apple Silicon" dice cosa fare. Il motivo arriva fino a `/api/status`
(campo `motori`) e alla pagina *Servizi & API*, così si scopre cosa manca guardando, invece
di sbatterci contro al primo clic:

```json
{ "motori": {
    "mlx":    { "usabile": false, "motivo": "MLX richiede Apple Silicon (Mac M1 o successivi). Su altro hardware si usa Ollama." },
    "ollama": { "usabile": true,  "motivo": "" }
} }
```

E se non ce n'è **nessuno**, non è un errore e POE parte comunque: l'estrazione non usa LLM.

Su Apple Silicon il modello MLX predefinito è `Meta-Llama-3.1-8B-Instruct-4bit`, scelto con
un benchmark su 4 modelli con verifica adversariale anti-allucinazione — metodo e punteggi
in [`TestLLM/VALUTAZIONE.md`](TestLLM/VALUTAZIONE.md).

---

## Personalizzazione

Tutto si configura **dall'interfaccia** (status bar → **API**, pagina *Servizi & API*)
**oppure** da `.env`. Le due strade scrivono lo stesso file: la scelta fatta dalla UI viene
salvata in `.env` e sopravvive al riavvio. Parti da `.env.example`, che documenta ogni
variabile.

### Scegliere motore e modello

```bash
POE_LLM_BACKEND=          # vuoto = POE sceglie; oppure mlx | ollama | openai | claude
POE_LLM_MODEL=            # vuoto = predefinito del motore
```

Una scelta esplicita vince, **ma solo se realizzabile**: chiedere `mlx` su un PC non-Apple
non lo fa funzionare, e POE ripiega dicendolo. Per il motore Claude i modelli ammessi sono
`opus`, `sonnet`, `haiku` (vuoto = predefinito).

Server compatibile OpenAI:

```bash
POE_OPENAI_BASE_URL=http://localhost:1234/v1   # deve finire con /v1
POE_OPENAI_MODEL=qwen3-8b                      # come lo chiama quel server
POE_OPENAI_API_KEY=                            # opzionale
POE_OPENAI_TIMEOUT=120
```

Il cambio motore vale **subito, senza riavvio**, anche via `POST /admin/llm/backend`.

### Chiavi API: cosa cambia con quale chiave

**Nessuna è obbligatoria.** Senza chiavi la pipeline deterministica funziona per intero, i
feed reputation locali funzionano, e i servizi a chiave restano link esterni cliccabili nel
catalogo. Nessuna funzionalità si rompe.

| Chiave | IOC | Costo | Cosa aggiunge |
|---|---|---|---|
| `ABUSEIPDB_API_KEY` | IP | free 1000/giorno | segnalazioni di abuso + confidence score in scheda |
| `VIRUSTOTAL_API_KEY` | URL, hash | free 4/minuto | verdetto aggregato di 70+ motori AV |
| `SHODAN_API_KEY` | IP | free limitato | dati host più ricchi (org/ISP/OS). Senza, POE usa già InternetDB, gratuito e senza account |
| `ABUSECH_API_KEY` | IP, dominio, URL, hash | **gratuita** | ThreatFox + URLhaus live (una sola Auth-Key per entrambi) |
| `OTX_API_KEY` | tutti | **gratuita** | pulse di threat-intel community |
| `HUNTER_API_KEY` | email | free 25/mese | recapitabilità di un indirizzo |
| `IPQS_API_KEY` | email, telefono | free limitato | fraud score |
| `NUMVERIFY_API_KEY` | telefono | free 100/mese | validazione live: paese, operatore, tipo linea |
| `EMAILREP_API_KEY` | email | opzionale | alza il rate limit; EmailRep funziona anche senza |

Le prime otto si incollano e si **testano** dalla UI, con un bottone che fa una query reale
al click (mai un ping periodico: la quota la consuma chi decide). `EMAILREP_API_KEY` si
imposta solo da `.env`.

### Altre variabili utili

```bash
POE_LLM_WARMUP=0      # niente warmup all'avvio: boot più rapido, prima risposta più lenta
POE_MCP_LIVE=1        # abilita il tier LIVE_KEYLESS dei tool MCP
POE_DEMO_DATA=1       # popola il DB con osservazioni sintetiche (solo sviluppo)
```

`.env` è in `.gitignore` e non finisce mai in un commit.

---

## Usare POE da fuori

L'interfaccia è HTMX: quasi tutte le rotte restituiscono **frammenti HTML** per la UI e non
sono pensate per un client esterno. Quelle utili a un programma sono queste.

### `POST /api/analyze` — testo → entità, in JSON

Di base non tocca nulla: nessuna scrittura, nessuna rete. Tre flag opzionali lo portano
dall'estrazione pura all'analisi completa, uno strato per volta:

| flag | cosa aggiunge |
|---|---|
| `save` | l'osservazione resta in cronologia e ri-apribile, invece di sparire con la risposta |
| `enrich` | geolocalizzazione e WHOIS: senza, si ricevono valori nudi |
| `lookups` | reputazione e minacce dalle fonti live. Senza, "pulito" e "non ho guardato" sono indistinguibili |

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text": "traffico sospetto da 45.33.32.156", "enrich": true, "lookups": true}'
```

Risposta: `count`, `entities[]`, `observation_id` (se `save`), `lookups{}` (se `lookups`).

I flag sono disattivati di default perché l'endpoint ha già chiamanti che vogliono la sola
estrazione, senza effetti collaterali. Con `lookups` la chiamata dura quanto la fonte più
lenta — decine di secondi — e ogni fonte che non risponde viene **riportata come tale**, non
omessa: sapere che una fonte non ha risposto e sapere che non ha trovato nulla portano a
conclusioni opposte.

### Le altre rotte JSON

| Rotta | A cosa serve |
|---|---|
| `GET /health` | readiness: `200` quando è pronto, `503` mentre carica. Per orchestratori e healthcheck |
| `GET /api/status` | stato dei componenti con un segnale reale: motori AI disponibili e perché, freschezza dei feed reputation, raggiungibilità dei servizi a chiave |
| `GET /api/tools` | inventario del catalogo OSINT interrogabile, raggruppato per categoria |
| `GET /e/{id}/export.json` | report completo di un'osservazione salvata, machine-readable |
| `GET /e/{id}/export.md` | lo stesso report in Markdown |
| `POST /admin/llm/backend` | cambia motore e modello a runtime, senza riavvio |
| `POST /admin/llm/unload` · `/admin/llm/warm` | cedono e riprendono la VRAM del modello locale, per convivere con un altro processo che ne ha bisogno sulla stessa macchina |

L'interfaccia è incorporabile in un overlay `iframe`, ma **solo da localhost**: la CSP
dichiara `frame-ancestors 'self' http://127.0.0.1:8000 http://localhost:8000`.

### Connettore MCP

`poe_mcp/` espone un sottoinsieme **vettato** di POE a Claude Code e Claude Desktop via MCP
su stdio. Sicurezza ad allowlist di tier, non a discrezione del modello:

- **`LOCAL`** — sempre attivo, 7 tool: analisi testo, decodifica codice fiscale, dati
  telefono, Google dork, catalogo risorse, reputation locale, stato del connettore. Compute
  locale: niente rete, niente scritture, niente segreti
- **`LIVE_KEYLESS`** — opt-in con `POE_MCP_LIVE=1`, oggi 1 tool (crt.sh): rete idempotente,
  senza quota
- **`GATED`** e **`FORBIDDEN`** — dichiarati ma **mai registrati**; i test verificano che
  restino fuori. Ci stanno la lettura del DB con PII, i lookup a chiave, le scritture e il
  reset

Vedi [`poe_mcp/README.md`](poe_mcp/README.md).

---

## Test

```bash
uv run pytest          # 839 passed, 1 skipped
uv run ruff check .
uv run bandit -r app poe_mcp -ll
```

---

## Architettura

```
app/
  main.py            FastAPI + route (HTMX, server-side rendering)
  recognizer.py      orchestratore estrazione
  extractors/        regex, spaCy
  enrichers/         geo IP (batch), WHOIS via RDAP
  reputation/        feed abuse.ch + blocklist.de, store e lookup locale
  llm/               availability (chi può girare qui) + backend MLX/Ollama/OpenAI/Claude + prompt
  live_lookup.py     28 lookup on-demand (25 verso servizi esterni, 3 locali)
  osint_catalog.py   catalogo risorse per tipo di IOC
  risk_scoring.py    punteggio e verdetto
  env_writer.py      scrittura .env dalla UI
  storage.py         SQLite
poe_mcp/             connettore MCP
static/              CSS + JS (nessun build step)
tests/               839 test
```

**UI**: HTMX + Jinja2, CSP stretta (`script-src 'self'`, niente `unsafe-inline`), interazioni
via event delegation — nessun `onclick` inline.

## Licenza

Proprietaria. Codice pubblicato a scopo dimostrativo.
