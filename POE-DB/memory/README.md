# POE-DB/memory — Memoria agenti AGNO

Questa cartella contiene il database SQLite della memoria persistente degli agenti.

- `poe_memory.db` — viene creato automaticamente al primo avvio di AGNO
- Non modificare manualmente
- Backup: copiare il file `.db` altrove

## Schema (gestito da AGNO)
- Tabella `poe_memory`: conversazioni e osservazioni per user_id
