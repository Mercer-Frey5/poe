# POE Voice Pipeline — Handoff tecnico

> Documento di passaggio consegne. La pipeline vocale di POE è **completa e funzionante**.
> Tutto ciò che serve per capirla, mantenerla e modificarla è qui.

Ultimo aggiornamento: 2026-06-11

---

## Cosa fa

Assistente vocale 100% locale su Mac M1 16GB:

```
Wake word ("Poe"/"Ei Poe", Chrome) → frase ack pre-renderizzata (voce POE)
  → cattura comando vocale → LLM (personalità POE) → TTS → RVC (timbro POE)
  → audio + trascrizione sincronizzata nella homepage
```

Tempo di risposta a regime: **~15-18 secondi** (LLM ~6s, TTS ~4s, RVC ~5-9s con mlx_rvc).
Modalità conversazione: dopo ogni risposta il microfono si riapre da solo (beep);
7s di silenzio → torna in attesa della wake word.

## Avvio

```bash
cd /Users/efrem-mac/Desktop/POE-AI/POE-Home
.venv/bin/python server.py
# Browser: http://127.0.0.1:8000  — SOLO CHROME (Safari crasha su SpeechRecognition continua)
```

Riavvio rapido: `lsof -ti:8000 | xargs kill -9; sleep 1; .venv/bin/python server.py`

Al boot il server stampa: caricamento LLM → TTS → RVC worker → `[POE] Prompt cache: N token` → `[POE] Pronto.`
Il browser mostra la splash finché `/health` non risponde `ready: true`.

## File

| File | Ruolo |
|------|-------|
| `server.py` | FastAPI: WS `/ws/speak` (pipeline completa), `/health`, `/ack/{n}`, `/log` (debug STT), `/logo`, `/` |
| `home_v1.html` | Frontend completo: splash, wake word, visualizer canvas, chat testuale, pannello trascrizione vocale |
| `gen_ack.py` | Rigenera i 32 WAV di ack (run manuale, skippa i file esistenti) — chiama Applio via subprocess inline (proprio venv), indipendente da `server.py`/mlx_rvc |
| `ack/ack_0..31.wav` | Frasi di conferma wake word pre-renderizzate con voce POE |
| `voices/poe/ref.wav` + `ref.txt` | Audio+testo di riferimento per il voice cloning del TTS Qwen (usato solo se `TTS_ENGINE="qwen"`) |
| `rvc_model/` | Modello RVC **attivo**: `poe-ita_200e_4200s.pth` + `poe-ita.index`, caricato direttamente da `server.py` via mlx_rvc |
| ~~`agents/`~~ | Skeleton AGNO archiviato (2026-06-10) in `../POE-Altro/POE-Home-archive/agents-skeleton-ollama/` — presupponeva Ollama, da riscrivere su mlx |

## Stack e modelli

| Componente | Modello/Tool | Note |
|-----------|--------------|------|
| LLM | `mlx-community/Qwen3.5-4B-OptiQ-4bit` (mlx-lm) | personalità POE nel `SYSTEM_PROMPT` di server.py |
| TTS | **Kokoro** `mlx-community/Kokoro-82M-bf16`, voce `im_nicola` | switch `TTS_ENGINE` in server.py: `"kokoro"` ↔ `"qwen"` (Qwen3-TTS 8bit, più fedele ma ~3x più lento) |
| RVC | **mlx_rvc** (`mlx-rvc==0.1.0`, lextoumbourou), modello `poe-ita_200e_4200s.pth` (epoch 200) + `poe-ita.index` | in-process, `RVCPipeline` caricata una volta al boot in `_rvc_pool` — ~2x più veloce di Applio |
| STT | Web SpeechRecognition API (Chrome) | nessun modello locale |

## Architettura server (server.py)

- **3 thread pool da 1 worker** (`_llm_pool`, `_tts_pool`, `_rvc_pool`): MLX Metal richiede
  che ogni modello viva sempre nello stesso thread.
- **RVC in-process (mlx_rvc)**: `RVCPipeline.from_pretrained()` caricata una volta al
  boot in `_rvc_pool` (`_rvc_load`), poi `_rvc_pipeline.convert(...)` per ogni richiesta
  (`run_rvc`). Niente più subprocess/JSON — sostituisce il vecchio `rvc_worker.py` (Applio).
  **Patch obbligatoria**: `mlx-rvc==0.1.0` estrae feature ContentVec a 50fps ma il
  synthesizer v2/40kHz + RMVPE f0 ne aspettano 100fps — senza upsample 2x l'output
  esce a metà durata (2x velocità). Fix via monkeypatch su `RVCPipeline._extract_contentvec`
  in `_rvc_load()` (server.py), applicato a runtime — non tocca i file installati nel venv.
- **Prompt cache LLM**: il KV del system prompt è pre-calcolato al boot (Qwen3.5 usa
  `ArraysCache`, non trimmabile → pattern snapshot/restore prima di ogni richiesta).
  Fallback automatico al percorso senza cache se i token non combaciano.
- **WS protocol**: client invia `{"text": ...}` → server risponde
  `{"type":"token","content":...}`× N (streaming, il frontend li ignora di proposito) →
  `{"type":"text","content":full}` → bytes WAV → `{"type":"done"}`.
  Su errore: `{"type":"error","content":...}` (mai più freeze silenziosi).

## Frontend (home_v1.html) — punti critici

- **AudioContext unlock**: buffer silenzioso riprodotto dentro il gesto utente in
  `_doSpeak()` — senza questo l'audio non parte dopo lunghe attese. NON RIMUOVERE.
- **Ack**: pre-caricati come **blob URL** al ready e riprodotti con `Audio()` —
  non usare AudioContext per gli ack (la wake word non è un "gesto utente" e
  `resume()` resterebbe appeso). Safety net 10s: il mic si apre comunque.
- **Wake detection**: `_hasWake()` matcha "poe/po/poi/apple/epo" word-level +
  varianti fonetiche ("ehipo", "eipo"...). Dedup anti-stuck: stessa stringa
  entro 1.5s ignorata. `onend` ricrea sempre un'istanza fresca di SpeechRecognition.
- **Cattura comando**: 7s silenzio iniziale → torna a wake mode; primo parlato →
  tetto 14s; 2.5s di pausa dopo una frase finale → invio. Doppio beep = mic aperto.
- **Trascrizione**: appare SOLO sincronizzata con l'audio (reveal progressivo via rAF
  su `ctx.currentTime`). Il testo live dei token è disabilitato per scelta dell'utente.
- **Stringhe JS**: usare SOLO double quote ASCII — gli apostrofi italiani nei literal
  hanno già causato SyntaxError da smart-quotes.

## Parametri voce (rvc_worker.py — valori scelti a orecchio dall'utente)

```
pitch=4  f0_method="rmvpe"  index_rate=0.5  protect=0.5
filter_radius=5  clean_audio=True  clean_strength=0.5  hop_length=128
```
- pitch 4 = più squillante (l'utente trovava la voce troppo cupa a 0-2)
- rmvpe + filter_radius 5 = niente tremolio (fcpe tremolava, ma è ~2x più veloce)
- Stessi parametri duplicati in `gen_ack.py` — se cambi uno, cambia l'altro e rigenera gli ack.

Env var OBBLIGATORIE per il worker (già nel codice): `KMP_DUPLICATE_LIB_OK=TRUE`,
`OMP_NUM_THREADS=1` (senza → SIGSEGV su M1), `PYTORCH_ENABLE_MPS_FALLBACK=1`.
MPS è disabilitato via monkeypatch: testato, su questo setup non dà alcun guadagno (CPU≈GPU).

## Cose tentate e scartate (non riprovare senza motivo)

1. **Streaming a frasi spezzate** (sentence chunking TTS→RVC): provato, l'utente NON lo vuole — audio tutto insieme.
2. **MPS per RVC**: zero guadagno misurato (12.8s vs 12.6s su 15s audio). Resta CPU.
3. **Testo live durante la generazione**: implementato e poi disabilitato su richiesta (trascrizione doppia sgradita).
4. **Fine-tuning Qwen3-TTS**: strada abbandonata nel progetto precedente (POE-RVC). Non riaprirla.
5. **Qwen3-TTS bf16 come engine principale**: troppo lento (37-95s); l'8bit (~3.5x più
   veloce) resta disponibile con `TTS_ENGINE="qwen"` se serve massima fedeltà di prosodia.
6. **Qwen3-TTS voice cloning diretto** (TTS+timbro POE in un solo step, ref audio
   golden/golden2/native): audio pulito ma timbro/accento "straniero" — scartato.
   Pipeline resta Kokoro (TTS) → mlx_rvc (timbro POE).

## TODO aperti / prossimi passi

- [ ] **Ack con ElevenLabs**: l'utente genererà le 32 frasi con ElevenLabs e sovrascriverà
      `ack/ack_N.wav` (stessi nomi). Le 32 frasi esatte sono in `gen_ack.py` → `PHRASES`.
      Se i file saranno MP3 serve aggiungere conversione o servire `audio/mpeg`.
- [ ] **Rimuovere debug STT**: endpoint `POST /log` in server.py + le `fetch("/log",...)`
      in home_v1.html quando il wake word non servirà più debuggarlo.
- [ ] **Integrazione col resto di POE-AI**: gli `agents/` AGNO (OSINT/Diario/Analisi) non
      sono collegati alla pipeline vocale. Le tre voci di nav (OSINT/DIARIO/ANALISI) nella
      home sono placeholder (`setSection` cambia solo il sottotitolo).
- [x] Velocizzazione RVC: **fatto** — RVC ora gira su mlx_rvc (in-process, ~2x più
      veloce di Applio). `rvc_worker.py` rimosso (dead code); `gen_ack.py` resta su
      Applio via subprocess inline (one-shot, non perf-critical).

## Dipendenze esterne alla cartella

- `~/POE-Voice/Applio/` — installazione Applio (RVC), **non più usata da `server.py`**
  (sostituita da mlx_rvc). Resta per `gen_ack.py`/retraining. Modello attivo per
  produzione: `rvc_model/` qui (pth+index).
- Modelli HuggingFace in cache (`~/.cache/huggingface/`): Qwen3.5-4B, Kokoro-82M,
  Qwen3-TTS-8bit (per l'engine alternativo).
- Il training RVC è documentato in `/Users/efrem-mac/Desktop/POE-RVC/` (progetto concluso:
  dataset, script di prep, report). Per ri-allenare la voce serve il PC Windows (GTX 1660).
