# POE-OSINT — Entity Extraction Engine

Tool OSINT personale per l'estrazione **deterministica e verificabile** di entità da testo libero.
Pensato per indagini su persone (recapiti, identificatori, profili), con supporto secondario su
domini, IP, hash e altri indicatori.

> **Principio fondativo:** la base di POE è deterministica. Nessun LLM tocca mai i dati estratti —
> non inventa, non corregge, non riscrive entità. I modelli, quando entrano, sono ospiti su richiesta
> esplicita dell'Operatore, con ruoli distinti.

**Stato:** v0.5 · ~300 test · 100% locale, offline-first.

---

## Cosa fa

Incolli un testo, POE estrae e classifica le entità riconosciute, ciascuna marcata con un
**livello di confidenza onesto** (alta / media / bassa) che riflette la natura della verifica,
non il desiderio di sembrare affidabili.

**Tipi riconosciuti:** `email`, `phone` (normalizzazione E.164), `url`, `domain`, `ipv4`,
`hash_md5`, `hash_sha256`, `cve`, `username`, `social_handle`, `person_name`, `org_name`,
`address`, `tax_id` (codice fiscale IT con check digit), `vat_id` (P.IVA IT con check digit),
`birth_date`.

**Pipeline di estrazione:**
- **Regex** per i tipi a pattern forte (con verifica check digit dove esiste — confidenza alta per costruzione)
- **spaCy NER** (`it_core_news_lg` + `en_core_web_lg`) per nomi di persona e organizzazioni
- **Deobfuscatore** (`hxxp://`, `[.]`, `(at)`, `(dot)`) con ricostruzione della forma originale
- **Normalizzatori** (telefoni E.164 via `phonenumbers`, TLD su lista IANA)
- **Enricher opzionali** (IP, WHOIS, social) — attivati su richiesta, mai in automatico

**Trasparenza:** POE non filtra le entità a confidenza bassa. Le mostra tutte, marcate onestamente.
L'Operatore decide cosa pesare e cosa verificare altrove.

**Performance:** estrazione **sincrona, < 100 ms** su testi tipici — interamente in locale, nessuna
chiamata di rete sul percorso deterministico. Gli enricher che richiedono rete sono opzionali ed espliciti.

---

## Avvio

```bash
cd POE-OSINT
uv run uvicorn app.main:app --reload
# → http://localhost:8000
```

Docker opzionale (`docker-compose up`), setup locale diretto supportato su macOS / Linux / Windows.

---

## Stack

| Area | Scelta |
|------|--------|
| Linguaggio | Python 3.12 |
| Web | FastAPI + HTMX + Jinja2 (server-side rendering, niente build step) |
| Estrazione | regex deterministico + spaCy NER |
| Storage | SQLite locale |
| Ambiente | `uv` (Astral), lockfile deterministico |
| Deploy | Docker opzionale, locale diretto |

---

## Architettura — principi

1. **Base deterministica e verificabile.** Nessun LLM tocca i dati estratti.
2. **Confidenza onesta.** Ogni entità è marcata `high` / `medium` / `low` secondo il tipo di verifica.
3. **Offline-first con ridondanza investigativa.** Tutto ciò che si può fare in locale resta in locale;
   l'online è scelta esplicita. Per ogni domanda investigativa più strade, non un'autorità singola.

Dettaglio completo di principi, schema entità, roadmap e convenzioni di rilascio in
[`POE-OSINT/STATUS.md`](POE-OSINT/STATUS.md) e [`POE-OSINT/VERSION.md`](POE-OSINT/VERSION.md).

---

## Test

```bash
cd POE-OSINT
uv run pytest
```

~300 test su pipeline di estrazione, normalizzatori, check digit (`tax_id`/`vat_id`),
route FastAPI e HTML servito.

---

## Roadmap (sintesi)

```
v0.5  template dossier + catalogo OSINT popolato
v0.6  enricher Qwen locale + confidenza reward-based
v0.7  enricher Claude on-demand ("Chiedi a Claude")
V1.0  release stabile, tutto integrato
```

---

## 🚧 POE-Home — assistente vocale AI (work in progress)

Linea di ricerca parallela, **non parte del core OSINT stabile**: un'interfaccia ad
**assistente vocale 100% locale** per POE, su un solo MacBook M1 16GB. Sviluppo attivo,
API e UI soggette a cambiamenti.

**Stack / tool:**
- **LLM locale** — Qwen3.5-4B (quantizzato 4-bit) su [`mlx`](https://github.com/ml-explore/mlx), Apple Silicon
- **STT** — Web Speech API browser-side, attivazione a wake word ("Poe" / "Ei Poe")
- **TTS** — [Kokoro](https://github.com/hexgrad/kokoro) 82M (bf16) via `mlx-audio` (Qwen3-TTS 8bit opzionale)
- **Voice conversion** — **mlx_rvc** in-process (timbro di personaggio addestrato, modello RVC dedicato)
- **Backend** — FastAPI + WebSocket per lo streaming audio in tempo reale
- **Agenti** — [AGNO](https://github.com/agno-agi/agno) agent framework (router + tool calling)

**Fatto finora:** pipeline vocale end-to-end funzionante (wake word → STT → LLM → TTS → RVC → audio),
tutto in locale, nessun dato inviato; modalità duale voce/testo; router AGNO con tool calling.

### ⚡ Ottimizzazione & latenza

Far girare una pipeline vocale completa su una sola macchina consumer (M1, 16GB, ~11GB
realmente usabili per i modelli) è un problema di **budget di RAM e di latenza**. Numeri a regime:

| Stadio | Tempo |
|--------|-------|
| LLM (Qwen3.5-4B 4-bit) | ~6 s |
| TTS (Kokoro) | ~4 s |
| RVC (mlx_rvc) | ~5–9 s |
| **Totale a risposta** | **~15–18 s** |

Leve di ottimizzazione applicate (con misure):

- **RVC migrato da Applio/subprocess → `mlx_rvc` in-process** — ~**2× più veloce**. La pipeline
  è caricata una volta al boot; niente più fork di processo né serializzazione JSON per richiesta.
- **Prompt cache LLM** — il KV del system prompt (la "persona" di POE) è pre-calcolato al boot
  con pattern snapshot/restore: il costo del prompt si paga **una volta sola**, non a ogni risposta.
- **3 thread pool dedicati** (LLM / TTS / RVC, 1 worker ciascuno) — MLX Metal richiede che ogni
  modello viva sempre nello stesso thread: i modelli restano caldi, **zero reload** tra richieste.
- **Scelta TTS guidata dai benchmark** — Qwen3-TTS bf16 misurato a 37–95 s (troppo lento per la
  voce): si usa **Kokoro**; la variante Qwen 8bit (~3.5× più veloce del bf16) resta opzionale.
- **Patch ContentVec 50→100 fps** su `mlx_rvc 0.1.0` — senza l'upsample 2× l'audio usciva a metà
  durata; fix via monkeypatch a runtime, senza toccare il pacchetto installato.
- **MPS testato e scartato per RVC** — nessun guadagno misurabile (12.8 s vs 12.6 s su 15 s di
  audio): si resta su CPU, evitando complessità inutile.
- **Caricamento on-demand** dei modelli per rispettare il tetto di RAM (LLM 4-bit ~5–6 GB +
  STT + TTS caricati/scaricati dinamicamente).

**Prossimo passo:** collegare gli agenti AGNO al motore **POE-OSINT**, esposto come tool
dell'agente — così l'assistente potrà eseguire estrazioni OSINT su comando vocale.

---

## 🔭 Vision — cosa deve diventare POE

POE (*Personal Observation Engine*) nasce come tool OSINT e cresce verso un **assistente di
intelligence personale, 100% locale e self-hosted** su Apple Silicon (M1, 16GB). Niente cloud,
nessun dato inviato: tutto ciò che POE sa fare bene in locale resta in locale.

**End-state — build modulare, non framework monolitico.** Ogni stadio è un servizio indipendente:

```
wake word ("Poe"/"Ei Poe")  →  STT  →  router AGNO  →  LLM/agenti + tool  →  TTS + RVC  →  voce
                                        │
                                        └── canale schermo (chat grafica): dati strutturati
```

**Come si collegano i pezzi:**

- **POE-OSINT come tool dell'agente.** Il motore deterministico di entity extraction viene avvolto
  come tool MCP: l'assistente esegue estrazioni OSINT su comando vocale e ne mostra l'output
  strutturato nella chat.
- **Risposte a due canali.** La *voce* dà solo riassunti naturali e concisi (cosa fa, cosa rileva);
  il *contenuto tecnico* (entità, tabelle, dossier) vive nella chat grafica.
- **Due cervelli a tier.** Un modello 4B residente — **POE Core** (conversazione, router, tool, voce) —
  più un modello grande on-demand — **POE Think** (Qwen3 8B) — evocato solo per ragionamento intenso.
  Caricamento dinamico per rispettare il vincolo RAM (~11GB usabili).
- **Pochi agenti verticali, un solo LLM.** Router → modulo → tool, tutti sullo stesso modello che
  cambia prompt/tool — non una gerarchia di 20 agenti. Output Pydantic obbligatori (regola AGNO).
- **Memoria su Obsidian.** Note markdown interconnesse via wikilink come fonte di verità (niente
  vector DB), esposte agli agenti via plugin Local REST API / MCP. I moduli personali (Diario,
  Analisi) restano locali, fuori dal repo pubblico.

**Architettura a due fasi — officina vs esercizio.** La voce di POE si *allena* una tantum su
desktop con GPU CUDA (officina); a regime POE gira al 100% sul Mac, l'officina resta spenta.
L'inferenza RVC è leggera, è il training a volere la GPU.

> La sintesi qui sopra riassume la vision tecnica completa del progetto.

---

*POE osserva. Sempre.*
