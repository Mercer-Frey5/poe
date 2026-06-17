# POE-OSINT — Tool OSINT

Estrattore deterministico di entità OSINT. FastAPI + HTMX + spaCy + Ollama.

## Avvio
```bash
cd POE-OSINT
uv run uvicorn app.main:app --reload
# → http://localhost:8000
```

## Struttura
```
POE-OSINT/
  app/                # FastAPI application
    main.py           # Router principale
    extractors/       # regex, spacy, llm
    enrichers/        # ip, whois, social
    llm/              # OllamaBackend, LLMExtractor
    templates/        # Jinja2
    storage.py        # SQLite
    scoring.py        # score + grouping
  static/             # CSS + JS
  tests/              # 302 test, 92% coverage
  data/
    poe.db            # Database osservazioni (OSINT-specific)
  docs/               # Docs + specs + piani
  pyproject.toml
```

## DB
- `data/poe.db` — SQLite locale, solo dati OSINT
- Memoria agenti AGNO → `../POE-DB/memory/`

## Versione attuale: v0.5.0
