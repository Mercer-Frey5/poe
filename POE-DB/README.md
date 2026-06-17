# POE-DB — Database e memoria condivisi

Archivio centrale di POE: memoria degli agenti AGNO e Obsidian knowledge vault.

## Struttura
```
POE-DB/
  memory/
    poe_memory.db       # SQLite — memoria agenti AGNO (cross-sessione)
    README.md
  obsidian/             # Vault Obsidian — aprire con Obsidian app
    .obsidian/          # Config Obsidian
    Home.md             # Note index
    OSINT/              # Connessioni a POE-OSINT
    Diario/             # Journal personale
    Analisi/            # Report e analisi
    Risorse/            # Riferimenti e link utili
```

## Come usare Obsidian
1. Apri Obsidian
2. "Open folder as vault" → seleziona `POE-DB/obsidian/`
3. Il vault è già configurato con le cartelle base

## Memory DB (AGNO)
- `memory/poe_memory.db` — usato da DiaryAgent, OsintAgent, SynthesisAgent
- Path assoluto da usare in `agents/base.py`:
  ```python
  DB_PATH = Path(__file__).resolve().parents[3] / "POE-DB" / "memory" / "poe_memory.db"
  ```
