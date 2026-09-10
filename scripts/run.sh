#!/usr/bin/env bash
# POE-OSINT — launcher UNICO.
#
# Fa partire il server FastAPI (app.main:app via uvicorn) scegliendo il backend
# LLM d'avvio. Il backend è comunque cambiabile A RUNTIME dalla UI (picker
# "POE-AI" nella status bar) o via POST /admin/llm/backend — questo script
# imposta solo il default al boot.
#
# Senza flag decide POE: guarda cosa e' utilizzabile su questa macchina e
# rispetta la scelta salvata in .env dal pannello "Servizi & API". I motori
# locali vengono preferiti al cloud, quindi di norma nessun dato lascia il device.
#
# Uso:
#   ./scripts/run.sh                      # locale (MLX), porta 8000
#   ./scripts/run.sh --claude             # backend Claude (abbonamento, cloud)
#   ./scripts/run.sh --ollama             # backend Ollama locale
#   ./scripts/run.sh --openai             # server compatibile OpenAI (LM Studio, …)
#   ./scripts/run.sh --model qwen-4b      # override modello locale
#   ./scripts/run.sh --port 8001 --reload # opzioni extra passate a uvicorn
#
# Ogni flag NON riconosciuto (--port, --reload, --host, ...) va a uvicorn.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

backend=""             # vuoto = decide POE: rileva la macchina e legge .env
model=""               # POE_LLM_MODEL (locale) — vuoto = default del backend
uvicorn_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude)      backend="claude"; shift ;;
    --ollama)      backend="ollama"; shift ;;
    --openai)      backend="openai"; shift ;;
    --local|--mlx) backend="mlx";    shift ;;
    --model)       model="${2:-}";   shift 2 ;;
    --model=*)     model="${1#*=}";  shift ;;
    *)             uvicorn_args+=("$1"); shift ;;
  esac
done

case "$backend" in
  "")
    echo "[POE-OSINT] Motore LLM: lo sceglie POE — rileva cosa e' utilizzabile su"
    echo "            questa macchina e rispetta la scelta salvata in .env."
    echo "            Forzalo con --local, --ollama, --openai o --claude."
    ;;
  openai)
    echo "[POE-OSINT] Backend LLM = server compatibile OpenAI (POE_OPENAI_BASE_URL)."
    ;;
  claude)
    echo "[POE-OSINT] Backend LLM = CLAUDE (abbonamento). ⚠️  I dati AI escono verso il cloud Anthropic."
    echo "            Prerequisito: 'claude' installato e autenticato (claude mcp list ok)."
    ;;
  ollama)
    echo "[POE-OSINT] Backend LLM = OLLAMA (locale). Privacy-first."
    ;;
  *)
    echo "[POE-OSINT] Backend LLM = LOCALE (MLX). Privacy-first, nessun dato lascia il device."
    ;;
esac
echo "[POE-OSINT] Switch a runtime dalla UI (picker 'POE-AI') o POST /admin/llm/backend."

# La variabile si esporta SOLO se e' stato passato un flag. Prima si esportava
# sempre, col valore "mlx" cablato qui dentro: vinceva su quanto salvato in .env,
# quindi chi sceglieva un motore dal pannello se lo ritrovava sostituito al
# riavvio — e la scelta automatica non entrava mai in gioco.
if [[ -n "$backend" ]]; then
  exec env POE_LLM_BACKEND="$backend" POE_LLM_MODEL="$model" \
    uv run uvicorn app.main:app ${uvicorn_args[@]+"${uvicorn_args[@]}"}
fi
if [[ -n "$model" ]]; then
  exec env POE_LLM_MODEL="$model" \
    uv run uvicorn app.main:app ${uvicorn_args[@]+"${uvicorn_args[@]}"}
fi
exec uv run uvicorn app.main:app ${uvicorn_args[@]+"${uvicorn_args[@]}"}
