# POE — Version History

Questo file traccia cosa ogni versione di POE contiene e cosa è cambiato.
Aggiornato a mano a ogni rilascio.

Principio: ogni versione è funzionante end-to-end nel suo perimetro,
testabile, reversibile via tag Git.

---

## In sviluppo — POE gira sulla macchina di chi lo scarica

Non ancora rilasciato: `app/__init__.py` riporta tuttora `0.8.0`.

POE nasceva tarato su un Mac: il motore AI predefinito era MLX, scritto nel
codice, su qualunque hardware. Chi lo scaricava su Windows o Linux otteneva un
avviso, un ripiego silenzioso, e — se non aveva Ollama — un errore
incomprensibile al primo clic su una funzione AI.

### Il motore lo sceglie la macchina, e dice perche'
All'avvio POE guarda cosa e' davvero utilizzabile qui e sceglie di conseguenza,
preferendo i motori locali al cloud: se un motore gira su questa macchina, i
dati non escono. Una scelta esplicita in `POE_LLM_BACKEND` continua ad avere la
precedenza, ma solo se realizzabile — chiedere MLX su un PC non-Apple non lo fa
funzionare, e a quel punto vale di piu' un motore che parte.

Quando un motore non e' disponibile, POE dice **perche'**: non "MLX non
disponibile", ma "MLX richiede Apple Silicon". Il motivo arriva fino a
`/api/status` (campo `motori`) e alla pagina *Servizi & API*, cosi' si scopre
cosa manca guardando, invece di sbatterci contro.

Nessun motore disponibile **non e' un errore** e non blocca l'avvio:
l'estrazione degli indicatori e' deterministica e non usa LLM. Si perdono le
sole sintesi e analisi.

### Un quarto motore: qualunque server compatibile OpenAI
Chi usa LM Studio, llama.cpp in modalita' server, vLLM, LocalAI, OpenRouter o un
endpoint aziendale interno non aveva alcuna via, pur avendo tutti la stessa
identica API. Un solo backend li copre, perche' fra loro cambia l'indirizzo, non
il protocollo: si configura con `POE_OPENAI_BASE_URL` e `POE_OPENAI_MODEL`. La
chiave e' opzionale — se fosse obbligatoria resterebbero fuori proprio i server
locali, che sono il motivo per cui questo backend esiste.

### Si configura dall'interfaccia, e la scelta resta
Motore, modello e chiavi API si impostano da *Servizi & API* senza toccare file.
Ollama — l'unico motore che gira su qualunque hardware — prima era raggiungibile
soltanto da variabile d'ambiente, cioe' non scegliibile affatto per chi aveva
appena scaricato il progetto.

La scelta viene scritta su `.env` e sopravvive al riavvio: prima era volatile, e
si tornava al default senza che niente lo dicesse. Se il file e' in sola lettura
(container, permessi) la risposta lo dichiara invece di fingere.

### Sicurezza e privacy: il quarto motore corretto, il container non piu' root
Con quattro motori, "chi manda dati fuori" non era piu' "Claude": il backend
compatibile OpenAI puo' puntare a LM Studio sulla stessa macchina o a un
servizio come OpenRouter dall'altra parte del mondo, stesso protocollo, privacy
opposta. Veniva classificato sempre come "locale". Ora POE riconosce se
l'indirizzo e' su questa macchina o in rete privata — e solo in quel caso lo
conta come locale — e lo espone in `/api/status` (`kind: "local"` o `"cloud"`).
Quando il motore scelto all'avvio non e' locale, un avviso finisce nei log
prima che qualunque analisi parta, non dopo che l'utente lo scopre da solo.

Il lanciatore (`scripts/run.sh`) aveva un default `mlx` cablato ed esportava
SEMPRE `POE_LLM_BACKEND`, che vince su quanto salvato in `.env`: chi sceglieva
un motore dal pannello se lo ritrovava sostituito al riavvio, e la rilevazione
automatica appena introdotta non entrava mai in gioco. Ora la variabile si
esporta solo se e' stato passato un flag esplicito.

L'immagine Docker girava come root: nessun volume ne' dipendenza lo richiede, e
POE tratta dati altrui. Il container ora esegue con un utente non privilegiato
(uid 1000). **Chi usa Docker deve rendere `./data` scrivibile da quell'utente
prima di riavviare** — `chmod 777 data`, oppure `sudo chown -R 1000:1000 data`
se si vogliono permessi stretti — altrimenti POE non riesce a scrivere il DB.
Il comando e' in `docker-compose.yml` e nel README.

Le chiavi API non compaiono mai in un log o in un messaggio d'errore, nemmeno
quando un servizio esterno risponde male e l'errore si porta dietro l'URL
chiamato, chiave in query string compresa. Vale anche per il backend
compatibile OpenAI, dove la chiave viaggia solo negli header.

---

## v0.8.0 — il raw non si perde piu' (1 settembre 2026)

### `/api/analyze` diventa utilizzabile da un programma
L'endpoint estraeva le entita' e basta: nessun arricchimento, nessun
salvataggio. Chi lo chiamava riceveva valori nudi e la ricerca non lasciava
traccia, quindi la volta dopo andava rifatta da capo.

Ora tre flag opzionali lo portano dall'estrazione pura all'analisi completa, uno
strato per volta: `save` (l'osservazione resta in cronologia e ri-apribile),
`enrich` (geolocalizzazione e WHOIS) e `lookups` (reputazione e minacce dalle
fonti live). Restano tutti disattivati di default: l'endpoint ha gia' chiamanti
che vogliono l'estrazione pura, senza effetti collaterali e senza rete.

Con `lookups` le fonti girano in parallelo, e quelle che non rispondono vengono
**riportate come tali** invece di essere omesse. La differenza non e' formale:
"la fonte non ha risposto" e "la fonte non ha trovato nulla" portano a
conclusioni opposte, e confonderle fa leggere un'assenza di dati come
un'assoluzione. Era gia' successo — un IP con 156 segnalazioni su AbuseIPDB
descritto come legittimo, perche' chi analizzava vedeva solo la
geolocalizzazione.

### I lookup live diventano persistenti
I risultati dei lookup vivevano in un dict in RAM. Sembrava un dettaglio
implementativo, ma decideva cosa vedeva l'analisi AI:

- la **sintesi investigativa** vedeva zero dati live se l'utente non aveva prima
  espanso a mano le card degli IOC. Il pannello e' un bottone indipendente
  dall'espansione: cliccarlo per primo — il modo normale di usarlo — produceva
  un'analisi sul solo enrichment deterministico, senza che niente lo segnalasse;
- i **lookup on-demand** (WhatsMyName, Holehe) partono da un click successivo a
  quando l'analisi per-IOC e' gia' stata generata e messa in cache: il loro
  risultato non rientrava mai;
- gli **export dopo un riavvio** dichiaravano "solo enrichment automatico" anche
  per osservazioni pienamente arricchite;
- **ogni riapertura di una card ri-colpiva le API esterne**, bruciando quota per
  ridisegnare dati gia' ottenuti.

Ora c'e' una tabella `lookup_results` dedicata, non un allargamento di
`enrichment_json`: quel blob viene riscritto per intero a ogni salvataggio e
riletto a ogni lettura di osservazione, quindi farlo crescere avrebbe fatto
pagare il costo del raw anche alle rotte che non lo usano.

Due proprieta' coperte da test: **la PII muore con l'osservazione**
(`delete_observation` e `reset_db` cancellano anche i lookup — senza,
sopravviverebbe a un'eliminazione chiesta proprio per liberarsene), e **salvare
non puo' rompere un lookup** (e' un effetto collaterale: l'utente vede comunque
il dato che ha chiesto).

### Errori delle API: quota, chiave e piano non sono la stessa cosa
- **Numverify** segnala gli errori con status HTTP veri (401/403/429), non con
  200 + `success:false`. Il codice chiamava `raise_for_status()` prima di leggere
  il corpo, quindi sei cause diverse — chiave invalida, quota mensile esaurita,
  quota giornaliera, rate limit, https fuori piano, account sospeso —
  collassavano in "errore di rete o timeout". Il ramo che sapeva leggere il
  messaggio d'errore era codice morto.
- **IPQualityScore** mette la causa in `message`: la scartavamo e davamo sempre
  la colpa alla chiave. Con un free tier da 35 lookup al giorno l'esaurimento
  del credito e' lo scenario piu' probabile, ed era quello diagnosticato peggio.
  Ora si riporta anche il `request_id`, che IPQS chiede per l'assistenza.
- **abuse.ch**: il pulsante "Testa" del pannello dava il messaggio piu' povero di
  tutti mentre il lookup spiegava dove generare la chiave — al contrario di quel
  che serve a chi sta configurando.
- `follow_redirects=True` sulle chiamate IPQS, le uniche del file a non averlo.

### Test
767 (da 739). Le otto funzioni di verifica delle chiavi non avevano copertura
perche' si chiamano `test_*`: importarle per nome le fa raccogliere da pytest
come test. E la fixture che isola la suite dalle API key reali ne elencava tre
su nove, scritte a mano: la suite passava o falliva a seconda di quali chiavi
fossero configurate sulla macchina. Ora l'elenco viene dal registro dell'app.

## v0.7.0 — Persone, backend LLM commutabile, connettore MCP (31 agosto 2026)

Versione dell'applicazione allineata in un punto solo: `app/__init__.py`
(`__version__`), da cui la leggono FastAPI e la LABEL del Dockerfile.
Il `?v=` degli asset in `base.html` e' un contatore di cache-bust indipendente:
serve solo a invalidare la cache del browser, non e' la versione del prodotto.

### Lookup su persone (batch)
- **Codice Fiscale**: decodifica reversa 100% locale (data/luogo di nascita, sesso).
- **Google Dork** costruiti per tipo di IOC.
- **Wave A — 7 fonti keyless**: EmailRep, Hudson Rock, GitHub, Keybase, GitLab, Reddit.
- **Wave B — fonti con chiave**: IPQualityScore (email + phone), Numverify.
  HIBP **rimosso**: non ha piu' un free tier, teneva una voce morta nella UI.
- **WhatsMyName**: dataset di 719 siti vendorizzato in `app/config/wmn-data.json`,
  checker async concorrente, presenza username.
- **Holehe**: email -> account registrati, via subprocess.
- **Infrastruttura lookup on-demand**: le fonti pesanti non partono da sole
  all'espansione della card, ma con un bottone "Verifica".

### Backend LLM commutabile
- POE-OSINT puo' usare **Claude via abbonamento** (`claude -p`), non l'API a token.
  `ANTHROPIC_API_KEY` viene rimossa dall'ambiente del subprocess: garanzia
  strutturale di zero addebiti per-token.
- **Swap a runtime**: `POST /admin/llm/backend`, `kind` esposto in `/api/status`.
- **Picker "POE-AI"** nella status bar: tendina Locale/Claude + scelta modello.
- `scripts/run.sh`: launcher unico con `--claude` / `--ollama` / `--model`.

### Connettore MCP POE <-> Claude (`poe_mcp/`, v0.1)
Server MCP locale su stdio che espone a Claude Code/Desktop un subset vettato di
POE-OSINT. Sicurezza ad allowlist di tier: LOCAL sempre, LIVE_KEYLESS opt-in via
`POE_MCP_LIVE`, GATED e FORBIDDEN mai registrati.

### VRAM e UI
- **Handoff VRAM** hub vocale <-> POE-OSINT: un solo LLM in memoria alla volta,
  warm-on-enter entrando in modalita' OSINT.
- **Card IOC a due colonne** (info tool | Analisi AI) con splitter trascinabile,
  reset dblclick, frecce accessibili; stack responsive.
- **Sintesi investigativa** disponibile solo con piu' di un IOC.
- Status bar raggruppata, monitoraggio servizi con API live inline, tag con la
  parola intera invece della sola iniziale.

### Igiene e affidabilita' (questa release)
- **Igiene dati**: i database di lavoro non sono piu' tracciati da git. I pattern
  in `.gitignore` usavano uno slash interno, che li ancora alla radice del repo e
  li rende ciechi alle sottocartelle: ora usano `**/` piu' un catch-all `*.db`,
  cosi' valgono a qualsiasi profondita' per i moduli presenti e futuri. Un DB di
  osservazioni contiene PII reale e non deve mai finire in un commit.
- **Immagine Docker riparata**: `requirements.txt` era fermo a v0.3 mentre `app/`
  aveva iniziato a importare dotenv, httpx, ollama, reportlab, whois,
  markdown_it. Il Dockerfile installa da li', quindi il container non si
  avviava; il difetto era invisibile in locale, dove si usa `uv`.
  `docker-compose.yml` ora passa `.env` (opzionale) e imposta Ollama come
  backend in container.
- **`.env.example` completo**: era fermo a "POE v0.1 non richiede variabili
  d'ambiente" mentre il codice ne leggeva 17.
- **Test di guardia** contro le derive che hanno prodotto i punti sopra:
  allineamento pyproject/requirements/import reali/versione/LABEL Docker
  (`test_requirements_sync.py`), `.env.example` vs `os.getenv` reali
  (`test_env_example.py`), `[hidden]` battuto da `display:flex` e cache-bust
  disallineato (`test_static_assets.py`).
- abuse.ch: un 403 `unknown_auth_key` ora dice che la Auth-Key va generata
  (gratis) su auth.abuse.ch, invece di sembrare un limite di piano a pagamento.
- Favicon e apple-touch-icon dichiarate: basta 404 ripetuti nei log.

---

## v0.6.0 — Correlazione + Intelligence (5 luglio 2026)

Blocco completo di 5 sotto-progetti, ognuno con brainstorm→spec→piano→build e
review (per-task + whole-branch), tutti mergeable con 0 finding Critical/Important:

1. **Pivoting/relazioni** — tabella `entity_index`, query di co-occorrenza,
   badge `⇄N` sulle card, vista `/e/cross/{value}` con osservazioni + IOC correlati.
2. **Reputation** — feed abuse.ch (ThreatFox/URLhaus/Feodo/MalwareBazaar) scaricati
   e auto-aggiornati in locale (`reputation.db` separato), lookup 100% locale
   (nessuna rete al query-time), badge `⚠ malevolo` con fonte/minaccia.
3. **Risk scoring** — punteggio/verdetto per IOC (critico/sospetto/basso) da
   segnali esistenti (reputation/tld/pivot/bogon), pesi in YAML, riepilogo
   aggregato per osservazione.
4. **Catalogo OSINT** — popolato con risorse threat-intel (AbuseIPDB, crt.sh,
   urlscan.io, VirusTotal, MalwareBazaar, NVD, MITRE), deep-link diretti sulla
   card IOC ("Risorse esterne"); schema/loader fail-fast; ~20 risorse
   person_name pre-esistenti intatte.
5. **Report investigativo** — export `.md` arricchito (rischio, reputation,
   enrichment, correlazioni per IOC) sulla stessa route; nuovo export `.json`
   completo machine-readable.

Fix critico emerso in review (Risk Scoring): rimosso un prompt-cache MLX che
contaminava le risposte tra richieste diverse — mai arrivato in produzione,
trovato e corretto durante lo stesso ciclo di review.

---

## v0.5.1 — analyze deterministico + LLM on-demand/background + correlazione + UI (rilasciata, luglio 2026)

**Scopo**: rendere "Osserva" **istantaneo**, spostare l'LLM interamente on-demand/background,
arricchire in linea (geo batch + RDAP), **correlare** URL/email→dominio, e rifinire la UI.

### Analyze deterministico
- `/analyze` non chiama più l'LLM: solo **regex + spaCy** (NER-only via `exclude` pipe). Istantaneo.
  Elimina l'`address` allucinato che l'LLM produceva.
- **Enrichment dentro `/analyze`**, in parallelo con timeout (`EnricherRegistry.enrich_all`):
  geo IP via **ip-api `/batch`** (una sola chiamata per tutti gli IP, + `countryCode`), WHOIS domini
  via **RDAP** (veloce; rimosso il fallback `python-whois` porta-43 che causava timeout). Dati già
  in riga al primo paint, persistiti in `enrichment_json`.
- Guard spaCy: scarta `person_name` con `@`/cifre (FP tipo "contatto admin@x.com", "vulnerabilità CVE-...").

### LLM on-demand + background
Backend **MLX `llama-3.1-8b`**, **warmup all'avvio**, disattivato sotto pytest.
- `POST /e/{id}/entity-ai` — analisi AI del singolo IOC (lazy al primo expand).
- `POST /e/{id}/synthesis` — sintesi investigativa (invariata).
- `POST /e/{id}/extract-ai` — **"LLM Enricher"**: estrae org/indirizzi on-demand (fuori dal flusso veloce).
- **Validazione FP in background** (`_validate_low_entities`): dopo `/analyze`, l'LLM droppa i falsi
  positivi tra le entità *low* (es. "Connessioni" marcata `person_name` da spaCy).

### Correlazione URL/email → dominio (INVERTE la vecchia dedup)
L'host di un URL e il dominio di un'email diventano entità `domain` **correlate** (`derived_from`
+ `metadata.derived_source`), enrichibili e con badge "↳ da url/email". Vedi decisione in `STATUS.md`.

### UI (CSP-safe, asset `?v=0.5.8`)
- **Fix critico**: la CSP (`script-src` senza `unsafe-inline`) bloccava gli `onclick` inline →
  espansione IOC/CVE/stella rotti. Tutto migrato a **event-delegation** in `app.js` (CSP resta stretta).
- Card IOC: badge in ordine **INFO · correlazione · TAG** (separati); enrich-data IP = `ISP · 🏴 CC · città`
  (hover = nome paese); tag **`! whois`** giallo per domini non registrati (404 RDAP) + anno creazione;
  tag **`LLM`** con definizione.
- Fonti: vista **formattata** (kv-grid) di default + `raw` on-demand (macro `source_block`).
- Stella **Preferiti** per voce nelle osservazioni recenti; tasto **flush DB** (testing) → `POST /admin/reset`;
  bottoni più grandi; header/greeting compatti; layout più largo (1380px), meno bordi.

**Stato**: in corso su `dev`. ~15 commit, **330 test verdi**. Codice a `0.5.1`.

**Tag Git**: `v0.5.1` (da apporre allo squash su `main`).

---

## v0.5 — enricher + sintesi LLM + scope allargato (rilasciata, giugno 2026)

**Scopo**: arricchimento delle entità (enricher online) + lettura in prosa via LLM locale, e
allargamento dello scope a OSINT multi-dominio.

**Stato**: parzialmente rilasciata. Codice a `0.5.0` (FastAPI). Implementato:

- **Enricher** (`app/enrichers/`): `ip_enricher`, `whois_enricher`, `social_enricher` +
  `BaseEnricher` polimorfico (E2 di v0.4). Attivati on-demand per entità, registry in lifespan.
- **Sintesi LLM** (anticipata dalla roadmap v0.6): endpoint `POST /e/{id}/synthesis`. Backend
  **MLX nativo Apple Silicon** (`app/llm/mlx_backend.py`) — su Mac si usa MLX, non Ollama
  (Ollama resta per Docker/Linux). Modello **`llama-3.1-8b`** (MLX 4-bit), scelto col
  **benchmark OSINT v3** (`TestLLM/VALUTAZIONE.md`: overall 4.0, il più pulito sulle
  allucinazioni). Tono **professionale/neutro da analista, nessuna persona POE**. Prompt
  `synthesis.yaml` con guardrail anti-allucinazione (no WHOIS/ASN inventati, attribuzione
  "non confermato", pesare le contraddizioni). `max_tokens` 1100. Override `POE_LLM_MODEL`,
  backup `qwen-4b`.
- **Endpoint `POST /api/analyze`** (JSON: testo → entità deterministiche).
- **Catalogo OSINT** (`app/config/osint_catalog.yaml`): schema presente (popolamento in corso).
- **Scope allargato** (decisione 29 giugno 2026): da "ricerca su persone" a **threat-intel +
  cybersecurity + persone + info generali**, data-driven ("più lo utilizzo, più capiamo cosa
  serve"). Vedi `STATUS.md` → *Scope*.

**Manca (v0.5 fase 2)**: template **dossier**, **catalogo OSINT popolato**, dedup URL/email
fase 2, classificazione piattaforma su `social_handle`. In valutazione: output **JSON
strutturato** per la sintesi nel caso threat-intel (oggi la sintesi è prosa, coerente col
principio "LLM = prosa sopra base deterministica").

**Tag Git**: `v0.5` (da apporre quando la fase 2 chiude).

---

## v0.4 — fondazioni + idee piccole + idee grandi fase 1 (rilasciata, maggio-giugno 2026)

**Scopo**: consolidare le fondazioni del progetto (scope dichiarato,
due nuovi principi architetturali, schema entità esteso), implementare
una serie di idee piccole intere, e avviare in fase 1 quattro idee
grandi che maturano in v0.4 → v0.5.

**Stato**: ✅ implementata. Pianificata il 3 maggio 2026, costruita tra maggio e giugno
(confidence vocabulary, suspicious_tld, tipi persone tax_id/vat_id/social_handle/birth_date,
scoring osservazione, BaseEnricher). Test `tests/test_v04_*`.

**Stima di lavoro**: ~11.5 giorni effettivi. Più del doppio di v0.2 e
v0.3 (~5-7 giorni ciascuna), ma giustificato dalle fondazioni nuove
introdotte.

### Fondazioni

- **Scope dichiarato di POE**: registrato in `STATUS.md` come
  *"strumento personale di ricerca, prevalentemente su persone"*.
  Orienta la priorità dei tipi (tax_id, vat_id, social_handle,
  birth_date), il futuro catalogo OSINT, gli enricher LLM
- **Principio architetturale 3 — Trasparenza della confidenza**:
  registrato in `STATUS.md`. Ogni entità ha un livello di confidenza
  onesto, qualitativo (`high` / `medium` / `low`). POE non filtra
  entità a confidenza bassa, le mostra con marcatura onesta
- **Principio architetturale 4 — Offline-first con ridondanza
  investigativa**: registrato in `STATUS.md`. POE è prevalentemente
  offline, le funzionalità deterministiche restano in locale, le
  scelte online sono esplicite. Per ogni domanda esistono più strade,
  non un'autorità singola
- **Schema `Entity` esteso**: nuovi campi `confidence:
  Literal['high','medium','low']` e `metadata: dict` (per country_code,
  derived_from, ecc.). Backfill in lettura per entità di v0.2/v0.3
  (default `confidence='medium'`, `metadata={}`). Nessuna migrazione
  DB esplicita richiesta

### Idee piccole intere

1. **A1 — Country code phone in UI**: il `phone_normalizer` di v0.3
   produce già `country_code` e `national_number`. v0.4 li espone in UI
   (bandiera + nome paese). Esposti via `Entity.metadata`
2. **A2 — Phone con punti come separatori**: estensione regex per
   catturare formati tipo `347.123.4567`. Test bene contro IP, hash,
   URL che usano punti per altre ragioni
3. **A3'.2 — `tax_id` italiano con check digit**: nuovo tipo regex,
   16 caratteri alfanumerici con verifica del codice di controllo.
   Confidenza alta per costruzione
4. **A3'.3 — `vat_id` italiano con check digit**: nuovo tipo regex,
   11 cifre con verifica check digit. Confidenza alta
5. **B1 — Flag `suspicious_tld`**: lista statica curata in
   `app/config/suspicious_tlds.yaml` (~30 voci iniziali). Marca
   domini con TLD sospetto. Datata e versionata. Confidenza media
   (la lista evolve)
6. **C1' — Punteggio osservazione baseline**: algoritmo somma pesata
   delle confidenze entità (alta=3, media=2, bassa=1) + bonus per
   varietà di tipi. Normalizzato 0-100. Visibile nello storico
7. **C3 — Embrione export Markdown**: bottone "Esporta" nella vista
   dettaglio. Output Markdown statico (titolo, data, input, entità
   raggruppate per tipo con confidenza). Niente prosa narrativa
   (LLM in v0.6)
8. **E2 — `BaseEnricher` polimorfico (interfaccia astratta)**: classe
   `BaseEnricher` con metodo `enrich(entity) -> EnrichedEntity`.
   Solo definizione. Implementazioni in v0.6+ (Qwen) e v0.7 (Claude)

### Idee grandi — fase 1 (continuano in v0.5 fase 2)

1. **A3'.1 — `social_handle` come tipo (fase 1)**: riconoscimento
   del pattern `@handle`. Senza classificazione automatica della
   piattaforma. Confidenza media
2. **A3'.4 — `birth_date` con marcatori contestuali (fase 1)**: solo
   date precedute da marcatori espliciti ("nato il", "data di nascita",
   "DOB"). Confidenza bassa per costruzione (la data senza contesto
   è ambigua)
3. **A5 fase 1 — Schema `derived_from` in `Entity`**: solo campo nello
   schema, nessun cambio della logica di dedup. Prepara la fase 2 in
   v0.5 (URL/email producono entità domain derivata con relazione)
4. **C2 fase 1 — Cronologia curabile minimale**: flag `kept: bool`
   in DB osservazioni, vista filtrata semplice (tutto / solo kept /
   solo bozze). Niente note manuali, tag, eliminazione singola — quelli
   in v0.5 fase 2
5. **E1 fase 1 — Schema YAML del catalogo OSINT**: solo struttura
   dichiarativa (formato delle voci, campi obbligatori e opzionali).
   File vuoto. Popolamento del catalogo con risorse vere in v0.5 fase
   2, in coordinamento con chat *OSINT/Metodologia*

### UI — Visualizzazione confidenza

- Schema interno: `confidence: Literal['high', 'medium', 'low']`
- UI: colore (verde/giallo/rosso) + etichetta testuale
  ('Alta' / 'Media' / 'Bassa') + fascia indicativa di percentuale
  (es. "80-100%" per alta, "50-79%" per media, "0-49%" per bassa)
- Niente percentuale puntuale: il dato che POE ha è qualitativo,
  inventare un numero preciso sarebbe disonesto

### B2 — Flag `bogon` su IP — in coda

In coda nello scope di v0.4. Va implementato **solo se v0.4 chiude
sotto budget**. Costo basso (~1 giorno) ma valore d'uso modesto nello
scope "ricerca persone": gli IP bogon scattano raramente in indagini
personali. Se non entra in v0.4 slitta a v0.5 o v0.6.

### Cosa NON è in v0.4

- Catalogo OSINT popolato (solo schema in v0.4 fase 1, popolamento
  in v0.5)
- Template dossier (v0.5)
- LLM (v0.6 Qwen, v0.7 Claude)
- Sistema di confidenza reward-based (v0.6+, sessione architetturale
  dedicata)
- Logging strutturato (v0.6+)
- Test di regressione visiva con browser automatizzato (v0.5+)
- Tipi crypto (`bitcoin_address`, `ethereum_address`) — fuori scope
  "ricerca persone", non previsti
- Tipi SOC (`ipv6`, `asn`, `mac_address`) — fuori scope, non previsti
- Cronologia curabile completa (note, tag, eliminazione) — v0.5 fase 2
- Classificazione piattaforma su social_handle — v0.5 fase 2
- Revisione completa dedup URL/email → domain — v0.5 fase 2

### Test attesi

Stima ~30-40 nuovi test, di cui:
- Validazione check digit `tax_id` e `vat_id` (positivi e negativi)
- Estrazione `social_handle` con varianti
- Estrazione `birth_date` con marcatori
- Pattern phone con punti
- Calcolo punteggio osservazione su input campione
- Schema `confidence` e `metadata` su `Entity`
- Backfill in lettura per entità v0.3 (compatibilità storica)
- Export Markdown (snapshot test)
- Lista suspicious_tld caricamento e match

### Breaking change

- **Schema entità**: nuovi campi `confidence` e `metadata` su `Entity`.
  Backfill in lettura per `entities_json` storici (default `medium`,
  `{}`). Nessuna migrazione DB esplicita
- **`Entity` ha 5 campi ora**: `type`, `value`, `original`,
  `confidence`, `metadata`. Era 3 in v0.3

### Tag Git

`v0.4` (da apporre al rilascio)

---

## v0.3 — backend di base + cleanup theming + fix UX (rilasciata, maggio 2026)

**Scopo**: consolidamento della pipeline di estrazione (whitelist TLD
ufficiale, stoplist esternalizzata, normalizzazione phone E.164),
collasso del sistema multi-tema in identità visiva fissa, debito tecnico
cache busting saldato.

### Capitolo 1 — Cache busting

- Suffisso `?v=0.3.0` su `style.css` e `app.js` in `app/templates/base.html`
- Strategia: stringa hardcoded aggiornata manualmente a ogni rilascio
- Convenzione formalizzata in `STATUS.md` sezione "Convenzioni di rilascio"

### Capitolo 2 — Cleanup theming a singolo tema

- Sistema multi-tema rimosso: 7 blocchi `[data-theme="..."]` cancellati
- Palette `tech-mono` con asset locali Operatore migrata nel `:root` unico
- Anti-flash script eliminato, tendina selettore tema rimossa
- `app.js` ridotto a 3 responsabilità: `charCounter`, `copyButtons`,
  `submitOnEnter`
- Rimosso codice morto: `VALID_THEMES`, `applyTheme`, `getCurrentTheme`,
  `initThemeSwitcher`, persistenza localStorage del tema
- Google Fonts potato da 9 famiglie a 2: `IBM Plex Mono` + `Orbitron`
- Variabile `--font-brand` conservata per il logo POE (regola R3 in
  `STATUS.md`)
- Bilancio righe: `style.css` 909→604, `app.js` 175→131, `base.html` 87→51

### Capitolo 3 — Backend di base

- **IANA TLD list**: nuova cartella `app/config/`, file `tld_list.yaml`
  con seed di 140 TLD comuni, script `scripts/refresh_tlds.py` per
  refresh manuale via `data.iana.org`. Loader `_load_known_tlds()` in
  `regex_extractor.py` con fail-fast su file mancante o malformato
- **Stoplist `person_name` esternalizzata**: file
  `app/config/stoplist_person_name.yaml`, loader `_load_stoplist()` in
  `spacy_extractor.py` con stesso pattern fail-fast
- **Normalizzazione phone E.164**: nuova dipendenza
  `phonenumbers>=8.13.0`, modulo nuovo `app/phone_normalizer.py`. Default
  regionale italiano con rispetto del prefisso esplicito (es. `+44` UK
  riconosciuto correttamente). Pattern `original`/`value` esteso al
  phone. Numeri `is_valid_number=False` scartati silenziosamente.
  `NormalizedPhone` come `dataclass` con `e164`, `country_code`,
  `national_number`, `is_valid` — porta aperta a v0.4 (Recognizer di
  v0.3 usa solo `e164`)

### Fix UX — auto-aggiornamento sezione history

Promosso a v0.3 come scope creep accettato. Motivazione: comportamento
incoerente già latente in v0.2 (history non si aggiornava dopo
un'osservazione, richiedeva reload manuale).

- Pattern HTMX out-of-band swap (OOB) introdotto e formalizzato come
  regola R4 in `STATUS.md`
- Server in una sola response invia frammento principale (`#results`) +
  frammento OOB (`#history`)
- Wrapper `<section id="history">` sempre presente nel DOM, anche con
  DB vuoto
- Nuovo partial `_history.html` riusabile da `index.html` (server-side
  al primo GET) e `results.html` (frammento OOB del POST)
- Convenzione partial `_filename.html` formalizzata come regola R5 in
  `STATUS.md`
- Route `/analyze` ora calcola anche `recent = get_recent(10)` e lo passa
  al template

### Numeri

- Test automatici: 70 (v0.2) → 103 (v0.3), +33
- Nuovi file: 5 di codice/config + 4 di test
- File pre-esistenti modificati: 8
- Bilancio righe front-end: ~−380 (cleanup theming)

### Dipendenze

- Nuova: `phonenumbers>=8.13.0` (richiede `pip install -r requirements.txt`
  o aggiornamento ambiente)
- Rimosse a livello concettuale: 7 famiglie Google Fonts (caricate ma
  non più usate)

### Schema database

Invariato. Nessuna migrazione necessaria per upgrade da v0.2 a v0.3.
Regola formalizzata in `STATUS.md` sezione "Convenzioni di rilascio".

### Limiti noti registrati per v0.4+

- Phone con punti come separatori non catturato dal regex
- Dipendenza cross-modulo `regex_extractor → phone_normalizer`
  (accettabile per ora, da rivalutare se cresce)
- Refresh IANA TLD richiede rete (non air-gapped)
- `phonenumbers` aggiornamento dati regionali via pip

(Tutte registrate in dettaglio in `STATUS.md` sezione "Note aperte".)

### Tag Git

`v0.3`

---

## v0.2 — riverniciatura UI + robustezza pipeline (rilasciata, maggio 2026)

**Scopo**: prima vera personalizzazione dell'interfaccia e tre piccole
aggiunte di robustezza al backend deterministico.

### Front-end

1. **Sistema di theming via CSS custom properties**: tutti i colori e i
   font vivono in variabili CSS. Nessun valore hardcoded in HTML o codice.
   Vincolante come regola di design da qui in avanti.

2. **Quattro temi pre-costruiti** (slug tecnici esposti nell'UI):
   - `raven-elegante` — nero profondo + accenti oro/rame, serif elegante
   - `neon-cyber` — nero/blu + ciano-magenta neon, font sci-fi squadrato
   - `tech-noir` — grigio/nero caldo + ambra, IBM Plex (DEFAULT)
   - `signal-ops` — nero verdastro + verde fosforo, monospace ovunque

3. **Sistema font intercambiabile** con una coppia per tema. Caricamento
   da Google Fonts via un singolo link `?family=...` con `display=swap`.

4. **Selettore tema** (tendina nel header), persistenza via
   `localStorage["poe-theme"]`. Anti-flash via script inline in
   `<head>` che applica `data-theme` prima del rendering body.

5. **Microcopy POE concierge** (3 punti):
   - Saluto home: *"Buongiorno, Operatore. Le osservo con discrezione…"*
   - Placeholder textarea: *"Incolli qui ciò che desidera farmi osservare…"*
   - Spinner: *"Sto osservando…"*

6. **Tasti**: `Enter` lancia il submit, `Shift+Enter` (e altri modificatori)
   inserisce newline.

### Backend

7. **Stoplist label words italiane per `person_name`** in SpacyExtractor.
   Lista iniziale (~17 voci). Match esatto case-insensitive, scarto
   silenzioso. Fix del FP noto su "Contatto".

8. **Due nuovi tipi regex**: `hash_sha256` (64 hex), `cve` (`CVE-YYYY-NNNN+`).

9. **Deobfuscatore** in nuovo modulo `app/deobfuscator.py`.
   Sostituzioni: `hxxp://`, `hxxps://`, `[.]`, `[:]`, `(at)`, `(dot)`.
   Mantiene una `index_map` per ricostruire la forma originale dei
   match. Il Recognizer popola `Entity.original` quando differisce.

### Schema entità

`Entity` ora ha tre campi: `type`, `value`, `original`. In v0.1 i due
ultimi coincidevano per costruzione; il deobfuscator introduce la prima
divergenza reale. `original` ha default = `value` (post-init).

Visualizzazione: `original` mostrato in piccolo accanto a `value`
solo quando differisce.

### Test

70 test totali, tutti passanti.

### Dipendenze

Nessuna nuova dipendenza Python. Le famiglie font sono caricate
runtime da Google Fonts (no self-hosting in v0.2).

### Breaking change

- Schema entità: il campo `original` può divergere da `value`.
- Storage: schema della tabella invariato, MA il payload JSON
  `entities_json` ha un nuovo campo `original`. Backfill automatico
  in lettura per record v0.1 ancora presenti nel DB; raccomandata
  comunque la migrazione esplicita (`rm data/poe.db`).

### Note post-rilascio (sessione di refinement)

Dopo il rilascio v0.2, l'Operatore ha condotto una sessione di esplorazione
font/temi che ha prodotto:

- **Bug 1 (specificità CSS)**: blocco `:root` di fallback duplicato dopo
  i blocchi tema → vinceva sempre lui per posizione, sovrascrivendo i temi
  selezionati. Fixato unificando `:root` all'inizio del file.
- **Bug 2 (cache browser)**: dopo la fix, Chrome continuava a servire il
  CSS bugged perché cachato. Risolto con hard refresh, ma ha generato il
  debito *cache busting* poi saldato in v0.3.
- **Aggiunta sperimentale**: nuova variabile `--font-brand` (Orbitron in
  tutti i temi per il logo POE), e tre temi sperimentali (`tech-cyber`,
  `cyber-ops`, `tech-mono`).
- **Decisione strategica**: l'esplorazione si è chiusa con `tech-mono`
  scelto come unico tema definitivo. v0.3 ha collassato il sistema
  multi-tema.
- **Modifiche locali Operatore su tech-mono**: NON entrate in v0.2,
  preservate e applicate in v0.3.

### Tag Git

`v0.2`

---

## v0.1 — walking skeleton (rilasciata, aprile 2026)

**Scopo**: pipeline di riconoscimento grezzo di tipo di entità,
end-to-end, locale.

### Funzionalità

- Interfaccia web su `http://localhost:8000`
- Textarea multi-riga + bottone "Osserva"
- Output: entità raggruppate per tipo, ciascuna con bottone copia
- Storage SQLite, storico recenti, pagina di dettaglio
- Health probe su `/health`

### Tipi di entità riconosciuti (8)

`email`, `ipv4`, `url`, `domain`, `hash_md5`, `username`, `phone`, `person_name`

### Stack di estrazione

- Regex per 7 tipi a pattern forte
- spaCy NER (`it_core_news_lg` + `en_core_web_lg`) per `person_name`
- Whitelist TLD statica (~90 voci) per filtrare falsi positivi tipo
  "mario.rossi" → debito tecnico saldato in v0.3 (passaggio a IANA)

### Dedup

Se un dominio è coperto dall'host di un URL estratto o dalla parte
dopo `@` di un'email estratta, non viene emesso come entità `domain`
separata.

### Tag Git

`v0.1`

---

## Convenzioni di versionamento

- `v0.X` — rilasci minori che aggiungono funzionalità pianificate in roadmap
- `v0.X.Y` — patch di correzione su un rilascio `v0.X` esistente
- `V1.0` — prima release stabile con tutte le capacità di Livello 2 integrate
- Ogni rilascio è taggato in Git: `git tag v0.X.Y`

---

*POE osserva. Versione dopo versione.*
