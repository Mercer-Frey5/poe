# POE — Project Brief
> Documento di contesto autosufficiente. Scopo: dare a un'AI esterna (o a un umano)
> tutto ciò che serve per capire il progetto, fare ricerche mirate e proporre
> ottimizzazioni — ruolo "project manager orizzontale".
>
> Aggiornato: 2026-06-10. Da rigenerare a ogni milestone.

---

## 1. Cos'è POE

POE (Personal Observation Engine) è un **assistente AI personale 100% locale** su MacBook Air M1 16GB. Persona narrativa: il concierge Poe di *Altered Carbon* (doppiaggio italiano) — tono formale, eleganza vittoriana, si rivolge all'utente come "Signore"/"Sir". Parla con la **voce clonata del personaggio**.

Non è un chatbot generico: è un sistema modulare con interfaccia vocale primaria, UI grafica per il dettaglio, e moduli specializzati (OSINT, Diario, Analisi) attivabili a voce.

**Principi non negoziabili:**
- 100% locale, zero cloud, zero dati inviati (eccezioni future solo su permesso esplicito, es. Claude API per analisi complesse)
- Base deterministica e verificabile; **gli LLM sono ospiti, non host** — nessun LLM tocca/modifica i dati estratti dalle pipeline (vale soprattutto per OSINT)
- Voce = riassunti brevi e naturali; schermo = tutto il contenuto tecnico/strutturato (output a due canali)
- Offline-first

## 2. Stato attuale (2026-06-10)

| Componente | Stato |
|---|---|
| **Pipeline vocale** (POE-Home) | ✅ Completa: wake word → ack voce POE → comando → LLM → TTS+RVC → audio + trascrizione sincronizzata. ~21s/risposta |
| **POE-OSINT** | ✅ v0.3 rilasciata: pipeline deterministica estrazione entità + enrichment (geo/WHOIS) + FastAPI + UI. Ferma da maggio, stabile |
| **Voce POE (RVC)** | ✅ Modello `poe-ita` allenato (200 epoche, Applio, GTX 1660 Windows — fase "officina" conclusa, PC spegnibile) |
| **Agenti AGNO** | 🔴 Prossima fase. Vecchio skeleton (basato Ollama) archiviato perché superato |
| **Memoria persistente** | 🔴 Predisposta (POE-DB: SQLite + vault Obsidian configurato), nessun agente la usa |
| **POE-Diario / POE-Analisi** | 🔴 Placeholder (solo README + html vuoti) |

## 3. Struttura repo (`POE-AI/`)

```
POE-Home/      ← interfaccia principale: server.py (FastAPI), home_v1.html, worker RVC, ack/
POE-OSINT/     ← tool OSINT v0.3: app/, pipeline deterministica, tests, Docker
POE-Diario/    ← placeholder
POE-Analisi/   ← placeholder (visione: workspace di analisi con routing per complessità)
POE-DB/        ← memory/ (SQLite per agenti) + obsidian/ (vault configurato, cartelle OSINT/Diario/Analisi/Risorse)
POE-Altro/     ← archivi (skeleton AGNO vecchio, versioni precedenti home)
docs/          ← spec architettura (superpowers/specs/) + questo brief
WIN_file/      ← storico training F5-TTS su Windows (strada abbandonata)
```

Documenti chiave:
- `POE-Home/VOICE-PIPELINE.md` — handoff tecnico pipeline vocale (vincoli, parametri, decisioni scartate)
- `docs/superpowers/specs/2026-05-24-poe-ai-architecture-design.md` v0.2 — architettura layer AI + roadmap 8 fasi
- `POE-OSINT/STATUS.md` — stato e principi del modulo OSINT
- Report di ricerca esteso: `Report_Progetto_POE.html` (root del repo) — v2 con audit fattuale dei claim
  di Gemini/Perplexity/ChatGPT, RVC-MLX, STT su Neural Engine, doppio cervello, regole Agno

## 4. Stack tecnologico (runtime reale, Mac M1 16GB)

| Layer | Tecnologia | Note |
|---|---|---|
| LLM | `mlx-community/Qwen3.5-4B-OptiQ-4bit` via **mlx-lm diretto** in-process | ~2.5GB. Prompt cache del system prompt pre-calcolata al boot (snapshot/restore, Qwen3.5 usa ArraysCache non trimmabile). ~6s/risposta. **Niente Ollama**: introdurlo = secondo modello in RAM |
| TTS | **Kokoro** `Kokoro-82M-bf16` (mlx-audio), voce `im_nicola` | ~4s. Engine alternativo: Qwen3-TTS 8bit (`TTS_ENGINE="qwen"`), più fedele ma ~3x più lento |
| Voce/timbro | **RVC** (Applio), modello `poe-ita_200e_4200s.pth` + index | ~10s. Worker persistente in subprocess (venv Applio separato), protocollo JSON stdin/stdout. CPU (MPS testato: zero guadagno). Parametri: pitch 4, rmvpe, filter_radius 5 |
| STT + wake word | **Web SpeechRecognition API** (solo Chrome) | Zero RAM locale. Wake word "Poe"/"Ei Poe" via match testuale con varianti fonetiche. Provvisorio: upgrade pianificato = mlx-whisper + openWakeWord |
| Server | FastAPI + WebSocket (`/ws/speak`), porta 8000 | 3 thread pool da 1 worker (MLX Metal vuole ogni modello sempre nello stesso thread) |
| Frontend | HTML singolo (`home_v1.html`): splash, visualizer canvas, chat, trascrizione sincronizzata | Ack wake-word pre-renderizzati (32 WAV, blob URL). AudioContext unlock obbligatorio nel gesto utente |
| Dati | SQLite (OSINT + futura memoria agenti) + vault Obsidian | |

**RAM**: ~9GB totali, tutto residente — nessun load/unload necessario finora. Margine si erode con mlx-whisper (~1.5-2GB) o LLM più grande.

## 5. Decisioni prese (non rimetterle in discussione senza motivo forte)

1. **mlx-lm diretto invece di Ollama** — più veloce, prompt cache custom, un solo processo
2. **Kokoro + RVC invece di TTS fine-tuned** — fine-tuning F5-TTS/Qwen3-TTS tentato e abbandonato (qualità/tempi); Kokoro base + conversione RVC dà fedeltà migliore al timbro
3. **rmvpe invece di fcpe** per pitch RVC — fcpe ~2x più veloce ma tremolava (unica leva di velocizzazione RVC rimasta, da ritestare con base Kokoro)
4. **Audio tutto insieme, niente streaming a frasi** — provato, scartato dall'utente
5. **Niente testo live durante la generazione** — trascrizione solo sincronizzata con l'audio
6. **MPS disabilitato per RVC** — testato, CPU≈GPU su questo setup
7. **Risposte vocali brevi** (1-2 frasi) imposte dal system prompt — coerente col modello a due canali
8. **Moduli** = nome ufficiale delle sezioni specializzate (non "plugin"/"sezioni")
9. **POE è un'applicazione unica** (decisione 2026-06-10): OSINT/DIARIO/ANALISI non saranno
   app standalone ma **pagine di POE** — un solo server (POE-Home), un solo frontend, moduli
   serviti in-process. La pipeline OSINT v0.3 verrà assorbita (mount FastAPI o import Python
   diretto degli agenti), risolvendo anche il conflitto porta 8000. Il Docker standalone di
   OSINT diventa storico

## 6. Architettura target (prossime fasi)

```
Input (voce/testo) → Router (intent) → Agente del modulo (AGNO, stesso Qwen 4B
con prompt dedicato) → tool deterministici (es. pipeline OSINT) →
output duale { verbal: ≤30 parole per TTS, visual: dati strutturati per UI }
```

- **Applicazione unica**: POE-Home è l'unico server e l'unico frontend; i moduli sono pagine/viste
  della stessa app, le loro pipeline girano in-process (vedi decisione 9)
- **AGNO** come framework agentico (minimalista, LLM-agnostico, supporto MCP). Da collegare al Qwen mlx **già caricato** (via `mlx_lm.server` OpenAI-compatible o integrazione custom)
- **Memoria ibrida**: AGNO short-term (SQLite) + **Obsidian come fonte di verità long-term** (markdown + wikilink, esposto via plugin Local REST API / MCP)
- **MCP** come protocollo runtime per i tool; Printing Press come eventuale fabbrica build-time di CLI/MCP per API esterne (post-v1)
- **Self-healing** (launchd + watchdog) post-v1

## 7. Roadmap

| Fase | Stato |
|---|---|
| 1. Layer voce (wake word, TTS+RVC, STT) | ✅ Fatta (in variante browser) |
| 2. POE-Home core (FastAPI, UI, conversazione) | ✅ Fatta (manca solo output duale → fase 3) |
| 2.5 **Consapevolezza di base** (data/ora, device, salute sistemi) | ⬅️ In valutazione, prima di AGNO |
| 3. AGNO + Router + output duale | 🔴 Prossimo passo grosso |
| 4. Memoria (AGNO + Obsidian) | 🔴 |
| 5. Moduli (OSINT wrappato come tool, Diario, Analisi) | 🔴 |
| 6. Test end-to-end, 7. Fine-tuning mirato, 8. v1.0 | 🔴 |

**TODO minori aperti**: ack con ElevenLabs (32 frasi in `gen_ack.py`, sovrascrivere `ack/ack_N.wav`); rimozione endpoint debug `/log`; eventuale ritorno a fcpe per velocizzare RVC.

## 8. Punti deboli noti / aree di ottimizzazione

*(Aggiornato dopo il report v2 — diverse domande hanno già risposta verificata)*

1. **Latenza ~21s, collo di bottiglia RVC (10s)** → risposta dal report v2: **RVC-MLX**
   (`Acelogic/RVC-MLX` o `lextoumbourou/mlx-rvc`) — **primo esperimento da fare**. In alternativa
   **Path A**: eliminare RVC se Qwen3-TTS 0.6B Base clona il timbro POE abbastanza bene (A/B test).
   Non passare a fcpe: con RVC-MLX si tiene rmvpe e lo si accelera (1.82×)
2. **Dipendenza da Chrome** → risposta: STT sul **Neural Engine** (WhisperKit o Parakeet/FluidAudio),
   non mlx-whisper su GPU — lascia la GPU libera per LLM+TTS. openWakeWord per la wake word
3. **AGNO + mlx-lm** → confermato: agganciare il Qwen già caricato; adattare i tutorial Agno+Ollama
   al backend MLX. Struttura piatta Router → Modulo → Tool, un solo LLM condiviso
4. **Tool calling 4B** → risposta: regge se incanalato in **output Pydantic validati** e tool semplici;
   i fallimenti vengono dall'infrastruttura, non dal modello. PydanticAI per gli schemi, Agno per la regia
5. **Ragionamento complesso** → **doppio cervello**: POE Core (4B residente) + POE Think (Qwen3 8B
   on-demand, MAI residente su 16GB), escalation decisa dal router
6. **MCP**: solo 4 server (Obsidian, Filesystem, Shell, Browser); il resto = tool Python interni
7. **Obsidian Local REST API / MCP**: da verificare maturità plugin e ricerca ibrida leggera per M1.
   Graphiti: valutato e **rimandato post-memoria-base** (richiede graph DB, problematico con modelli piccoli)
8. **Backup remoto modello RVC**: index 194MB > limite GitHub. Git LFS vs alternativa
9. **Rischio n.1 trasversale: overengineering** — ogni aggiunta deve ridurre il costo di far
   funzionare/misurare/correggere il sistema, non aumentarlo

## 9. Hardware e vincoli

- **Runtime**: MacBook Air M1, 16GB unified memory (~11GB utilizzabili per modelli), macOS
- **Officina (conclusa)**: PC Windows i7-9700 + GTX 1660 6GB — usato solo per training RVC, ora non necessario
- Browser supportato: solo Chrome (Safari crasha su SpeechRecognition continua)
- Lingua di lavoro: italiano (modelli e dataset scelti di conseguenza)
