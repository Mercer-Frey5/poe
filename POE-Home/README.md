# POE-Home — Interfaccia principale

Home di POE: assistente vocale locale completo. Prossima fase: agenti AGNO.

**→ Per tutto ciò che riguarda la pipeline vocale leggi [VOICE-PIPELINE.md](VOICE-PIPELINE.md)** (handoff tecnico completo: architettura, parametri, decisioni prese, TODO).

## Avvio

```bash
cd POE-Home
.venv/bin/python server.py
# http://127.0.0.1:8000 — solo Chrome
```

## Struttura

```
POE-Home/
  server.py           # FastAPI: LLM + TTS + RVC + WebSocket
  home_v1.html        # Frontend: wake word, voice mode, chat, visualizer
  gen_ack.py          # Rigenera le frasi di conferma (ack/), via Applio inline
  ack/                # 32 frasi wake-word pre-renderizzate (voce POE)
  voices/poe/         # Audio di riferimento per TTS Qwen (engine alternativo)
  rvc_model/          # Modello RVC attivo (mlx_rvc), solo locale non in git
  VOICE-PIPELINE.md   # ← documento di handoff della pipeline vocale
```

## Agenti AGNO (prossima fase)

Il vecchio skeleton (basato su Ollama) è archiviato in
`../POE-Altro/POE-Home-archive/agents-skeleton-ollama/` — superato: il runtime reale
è mlx-lm in-process (vedi `server.py`). Gli agenti andranno scritti da zero collegandoli
al Qwen3.5-4B già caricato, con output duale `{verbal, visual}`.
La memoria degli agenti andrà in `../POE-DB/memory/poe_memory.db`.
Le voci OSINT/DIARIO/ANALISI nella nav della home sono placeholder in attesa dell'integrazione.
