# POE-Home/agents/general_agent.py
import json
import os
from datetime import datetime

from agno.agent import Agent
from agno.tools.calculator import CalculatorTools
from agno.tools.websearch import WebSearchTools

from .dual_output import DualOutput, VisualPayload
from .local_model import get_local_model
from .persona import SYSTEM_PROMPT
from .tools import POE_CITY, get_system_status, get_weather

# Tool il cui output va al pannello visual quasi crudo (spec §4.4):
# il risultato NON viene riassunto dal 4B, la voce dice solo una frase breve.
HEAVY_TOOLS = {"web_search", "search_news"}

# Ultimo tool eseguito (per il pannello STATUS). Aggiornato in run().
last_tool_used: str = "-"

_GIORNI = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica"]
_MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
         "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def _now_line() -> str:
    """Data/ora reale in italiano, ricalcolata a ogni richiesta. Prevale su
    qualunque conoscenza interna del modello (che sbaglia l'anno)."""
    n = datetime.now()
    return (f"Oggi e' {_GIORNI[n.weekday()]} {n.day} {_MESI[n.month - 1]} "
            f"{n.year}, ore {n.strftime('%H:%M')}.")


_TOOL_INSTRUCTIONS = (
    f"La citta' dell'utente e' {POE_CITY}: per meteo o ricerche locali senza "
    f"citta' esplicita usa {POE_CITY}, senza chiedere conferma.\n"
    "REGOLE TASSATIVE SUGLI STRUMENTI (non violarle mai):\n"
    "- Meteo o temperatura: DEVI chiamare get_weather. Non inventare MAI gradi "
    "o condizioni.\n"
    "- Notizie o attualita': DEVI chiamare search_news. Non inventare MAI notizie.\n"
    "- Ricerca o informazioni su qualcosa/qualcuno: DEVI chiamare web_search. "
    "Non inventare MAI fatti.\n"
    "- Calcoli aritmetici: DEVI usare la calcolatrice.\n"
    "- Domande su di te, sul computer, sulla posizione, RAM, uptime, strumenti: "
    "DEVI chiamare get_system_status.\n"
    "Se la domanda rientra in questi casi, chiama lo strumento PRIMA di "
    "rispondere: e' vietato rispondere a memoria.\n"
    "RISPOSTA VOCALE:\n"
    "- Dopo web_search o search_news di' UNA sola frase breve di "
    "accompagnamento (es. 'Sir, ecco la ricerca:' oppure 'Sir, le principali "
    "notizie sono queste:'): i dettagli compaiono gia' sul pannello visivo, NON "
    "elencarli e NON riassumerli a voce. Usa 'notizie' solo per search_news, "
    "'ricerca' per web_search.\n"
    "- Dopo get_weather, get_system_status o la calcolatrice NON c'e' pannello: "
    "pronuncia i dati nella frase. Esempi: 'Sir, a "
    f"{POE_CITY} ci sono 18 gradi e cielo coperto.' / 'Il risultato e' 42, "
    "Signore.'\n"
    "- Non dire MAI 'ecco i risultati' o 'le notizie sono queste' se in questo "
    "turno non hai chiamato web_search o search_news."
)

_agent = Agent(
    model=get_local_model(),
    description=SYSTEM_PROMPT,
    instructions=_TOOL_INSTRUCTIONS,
    tools=[
        get_weather,
        get_system_status,
        # backend="auto": fallback multi-motore (google/bing/brave...) — il solo
        # DuckDuckGo va in rate-limit / "No results found" sotto uso ripetuto.
        WebSearchTools(backend="auto"),
        CalculatorTools(include_tools=["add", "subtract", "multiply", "divide"]),
    ],
    # POE_DEBUG=1: dump completo AGNO (prompt, messaggi, tool call) — molto
    # verboso, solo per sessioni di debug approfondito.
    debug_mode=os.environ.get("POE_DEBUG") == "1",
    # Niente telemetria: assistente locale + il phone-home puo' bloccare l'avvio
    # se l'endpoint AGNO e' lento/irraggiungibile (gia' visto: import appeso).
    telemetry=False,
)


def _extract_visual(tool_executions) -> VisualPayload | None:
    """Primo tool pesante riuscito -> payload visual coi risultati crudi."""
    for t in tool_executions or []:
        if t.tool_name in HEAVY_TOOLS and t.result and not t.tool_call_error:
            try:
                results = json.loads(t.result)
            except (TypeError, ValueError):
                results = t.result
            return VisualPayload(
                type="search_results",
                data={"results": results,
                      "query": (t.tool_args or {}).get("query", "")},
            )
    return None


async def run(user_text: str) -> DualOutput:
    global last_tool_used
    try:
        # Data reale anteposta al messaggio: il 4B da solo sbaglia l'anno.
        prompt = f"[{_now_line()}]\n\n{user_text}"
        result = await _agent.arun(prompt)
        if result.tools:
            print("[TOOLS] " + ", ".join(
                f"{t.tool_name}({json.dumps(t.tool_args or {}, ensure_ascii=False)})"
                + (" ERRORE" if t.tool_call_error else "")
                for t in result.tools
            ))
            last_tool_used = result.tools[-1].tool_name
        verbal = (result.content or "").strip()
        return DualOutput(verbal=verbal, visual=_extract_visual(result.tools))
    except Exception:
        import traceback
        print("[GLITCH] AGNO run fallito:")
        traceback.print_exc()
        return DualOutput(
            verbal="Una lieve frammentazione degli archivi mi impedisce di "
                   "rispondere in questo momento, Signore.",
            visual=None,
        )
