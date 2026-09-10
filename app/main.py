"""
main.py — entry point FastAPI di POE v0.4.

Routes:
    GET  /                         pagina principale (filtro: ?view=all|kept|draft)
    POST /analyze                  analizza testo → ritorna HTML parziale (HTMX)
    GET  /e/{id}                   dettaglio di una singola osservazione
    POST /e/{id}/keep              toggle flag kept (HTMX)
    POST /e/{id}/label             salva label personalizzato (HTMX)
    POST /e/{id}/remove-entity     rimuove singola entità (HTMX)
    DELETE /e/{id}                 elimina osservazione intera (HTMX)
    GET  /e/{id}/export.md         export Markdown (C3)
    GET  /health                   probe di liveness
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # legge .env (API key servizi esterni) prima di ogni altro import applicativo

from app import __version__  # noqa: E402 (dopo load_dotenv, per contratto)

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from app.scoring import compute_accuracy, compute_score, group_by_type
from app.report import build_markdown_report, build_json_report
from app.pdf_report import build_pdf_report
from app.extractors.regex_extractor import RegexExtractor
from app.extractors.spacy_extractor import SpacyExtractor
from app.recognizer import Recognizer
from app.storage import (
    add_entities,
    counts_for_values,
    DB_PATH,
    delete_observation,
    ensure_index,
    get_by_id,
    get_enrichment,
    get_lookup_results,
    get_recent,
    get_synthesis,
    save_lookup_result,
    init_db,
    observations_with_value,
    related_entities,
    remove_entity,
    reset_db,
    save_enrichment,
    save_observation,
    save_synthesis,
    set_kept,
    set_label,
)
from app.llm.ollama_backend import OllamaBackend
from app.extractors.llm_extractor import LLMExtractor
from app.enrichers import EnricherRegistry
from app.enrichers.ip_enricher import IPEnricher
from app.enrichers.whois_enricher import WHOISEnricher
from app.enrichers.social_enricher import disambiguate_platform
from app.enrichers.reputation_enricher import ReputationEnricher
from app.reputation.store import init_rep_db, feed_status, is_stale
from app.reputation.updater import refresh_stale
from app.reputation.feeds import load_feeds
from app.env_writer import write_env_keys
from app.risk_scoring import compute_risk, aggregate_observation_risk
from app.osint_catalog import resources_for_type, resource_url, load_catalog
from app.ip_info import private_ip_info
from app.live_lookup import (
    crtsh_lookup, nvd_lookup, urlscan_lookup, cymru_asn_lookup, abuseipdb_lookup,
    virustotal_lookup, shodan_lookup,
    gravatar_lookup, xposedornot_lookup, phone_info_lookup,
    codice_fiscale_lookup, dorks_lookup,
    emailrep_lookup, hudsonrock_email_lookup, hudsonrock_username_lookup,
    github_api_lookup, keybase_api_lookup, gitlab_api_lookup, reddit_api_lookup,
    ipqs_email_lookup, ipqs_phone_lookup,
    numverify_lookup, whatsmyname_lookup, holehe_lookup,
    threatfox_lookup, urlhaus_lookup, otx_lookup, hunter_verify_lookup,
    test_abuseipdb_key, test_virustotal_key, test_shodan_key,
    test_abusech_key, test_otx_key, test_hunter_key,
    test_ipqs_key, test_numverify_key,
)
from app.service_health import site_reachability

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 50_000
_RECENT_LIST_LIMIT = 30  # "Osservazioni recenti": era 10, troppo poco con più di 10 osservazioni


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # Embedding consentito SOLO dall'hub vocale in locale (overlay iframe); altrove
        # bloccato. frame-ancestors sostituisce X-Frame-Options: DENY.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "  # htmx ora locale (static/htmx.min.js), niente CDN
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            "font-src 'self' https://fonts.gstatic.com; "
            "frame-ancestors 'self' http://127.0.0.1:8000 http://localhost:8000;"
        )
        return response

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Mapping region ISO-3166-1 alpha-2 → nome display italiano
_REGION_NAMES: dict[str, str] = {
    "IT": "Italia",      "US": "USA",          "GB": "UK",
    "DE": "Germania",    "FR": "Francia",       "ES": "Spagna",
    "CH": "Svizzera",    "AT": "Austria",       "BE": "Belgio",
    "NL": "Olanda",      "PT": "Portogallo",    "PL": "Polonia",
    "RO": "Romania",     "SE": "Svezia",        "NO": "Norvegia",
    "DK": "Danimarca",   "FI": "Finlandia",     "GR": "Grecia",
    "CZ": "Rep. Ceca",   "HU": "Ungheria",      "SK": "Slovacchia",
    "HR": "Croazia",     "RU": "Russia",        "UA": "Ucraina",
    "TR": "Turchia",     "CN": "Cina",          "JP": "Giappone",
    "KR": "Corea Sud",   "IN": "India",         "AU": "Australia",
    "CA": "Canada",      "BR": "Brasile",       "AR": "Argentina",
    "MX": "Messico",     "ZA": "Sud Africa",    "EG": "Egitto",
    "SA": "Arabia Saud.","AE": "Emirati Arabi", "IL": "Israele",
    "LU": "Lussemburgo", "IE": "Irlanda",       "SG": "Singapore",
    "HK": "Hong Kong",   "TW": "Taiwan",        "TH": "Thailandia",
    "VN": "Vietnam",     "MY": "Malaysia",      "ID": "Indonesia",
    "PH": "Filippine",   "NG": "Nigeria",
}


def _region_to_flag(region: str) -> str:
    """Converte codice ISO-3166-1 alpha-2 in emoji bandiera. "IT" → "🇮🇹" """
    if not region or len(region) != 2:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in region.upper())


def _region_to_label(region: str) -> str:
    """Restituisce "🇮🇹 Italia" o "🇬🇧 UK", oppure solo il region code."""
    flag = _region_to_flag(region)
    name = _REGION_NAMES.get(region.upper(), region)
    return f"{flag} {name}" if flag else region


def _build_backend(kind: str, model: str = ""):
    """Costruisce un backend LLM per `kind` ('mlx'|'claude') e `model`. Usato
    all'avvio (_make_llm_backend) e dallo swap runtime (POST /admin/llm/backend).
    Modello NEUTRO (no persona): i prompt OSINT controllano estrazione/sintesi."""
    kind = (kind or "mlx").lower()
    if kind == "claude":
        # Claude via ABBONAMENTO (Claude Code headless), non API a token. OPT-IN:
        # copre tutte le zone AI. NB privacy: i dati escono verso il cloud Anthropic.
        from app.llm.claude_backend import ClaudeCodeBackend
        logger.info("LLM backend: Claude Code (abbonamento) model=%s", model or "default")
        return ClaudeCodeBackend(model=model)
    if kind == "openai":
        # Qualunque server che parli il protocollo OpenAI: LM Studio, llama.cpp,
        # vLLM, LocalAI, OpenRouter, un endpoint aziendale. Fra loro cambia
        # l'indirizzo, non il protocollo, quindi un backend solo li copre tutti.
        from app.llm.openai_backend import OpenAICompatBackend
        return OpenAICompatBackend(model=model)
    if kind == "mlx":
        try:
            from app.llm.mlx_backend import MLXBackend
            # llama-3.1-8b: vincitore del benchmark OSINT v3 (TestLLM/VALUTAZIONE.md) — il piu'
            # pulito sulle allucinazioni + attribuzione prudente ("unconfirmed"), il piu' veloce
            # usabile su 16GB. Backup: qwen-4b via POE_LLM_MODEL. I guardrail anti-allucinazione
            # sono nei prompt synthesis*.yaml.
            return MLXBackend(model=model or "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit")
        except Exception:
            logger.warning("MLX backend non costruibile, fallback Ollama")
    return OllamaBackend(model=model or "qwen3.5:9b-q4_K_M")


def _make_llm_backend():
    """Backend LLM d'avvio: la macchina decide, l'utente ha l'ultima parola.

    Il default era `mlx` scritto nel codice, su qualunque hardware: chi scaricava
    POE su Windows o Linux otteneva un avviso e un ripiego silenzioso su Ollama,
    e — se Ollama non c'era — un errore incomprensibile al primo clic su una
    funzione AI. Ora si guarda cosa e' davvero utilizzabile qui (vedi
    `app/llm/availability.py`) e si sceglie di conseguenza, preferendo i motori
    locali al cloud: se un motore gira su questa macchina, i dati non escono.

    `POE_LLM_BACKEND` resta la scelta esplicita dell'utente e ha la precedenza —
    ma solo se realizzabile. Chiedere MLX su un PC non-Apple non lo fa
    funzionare, e a quel punto vale piu' un motore che parte."""
    import os

    from app.llm.availability import backend_predefinito, rileva

    pref = os.environ.get("POE_LLM_BACKEND", "").strip().lower()
    model = os.environ.get("POE_LLM_MODEL", "")

    disponibili = rileva()
    scelto = backend_predefinito(disponibili, pref)

    if scelto is None:
        # Nessun motore AI. NON e' un errore: l'estrazione e' deterministica e
        # funziona per intero. Si perdono solo sintesi e analisi per-IOC.
        logger.warning(
            "Nessun motore AI utilizzabile qui. POE funziona lo stesso: "
            "l'estrazione non usa LLM. Per abilitare l'analisi — %s",
            " | ".join(f"{b}: {disponibili.motivo(b)}" for b in ("ollama", "claude")),
        )
        scelto = "ollama"       # costruito ma inerte finche' il servizio non c'e'
    elif pref and pref != scelto:
        logger.warning("POE_LLM_BACKEND=%s non utilizzabile qui (%s) — uso %s",
                       pref, disponibili.motivo(pref), scelto)
    else:
        logger.info("Motore AI: %s (disponibili: %s)",
                    scelto, ", ".join(disponibili.pronti()) or "nessuno")

    app.state.llm_disponibilita = disponibili
    backend = _build_backend(scelto, model)

    # SICUREZZA: se il motore scelto fa uscire i dati (Claude, o un endpoint
    # OpenAI-compatibile non locale), va detto AL BOOT — nei log, dove chi
    # gestisce l'istanza lo vede subito — non lasciato scoprire aprendo
    # l'interfaccia dopo che l'analisi e' gia' partita.
    if _llm_kind(backend) in ("cloud", "claude"):
        logger.warning(
            "Motore AI '%s': i dati analizzati (indicatori, testo) escono "
            "verso un servizio esterno. Per restare in locale usa mlx, ollama, "
            "o un endpoint OpenAI-compatibile su localhost/rete privata.",
            scelto,
        )
    return backend


def _llm_kind(llm) -> str:
    """'claude' se ClaudeCodeBackend, 'cloud' se un backend OpenAI-compatibile
    punta a un indirizzo non locale, altrimenti 'local' (MLX/Ollama/OpenAI-
    compat su localhost). Per class-name per evitare import a modulo dei
    backend opzionali.

    SICUREZZA: questo valore alimenta /api/status e la status bar — è il
    segnale con cui l'utente sa se i suoi dati restano sul dispositivo. Un
    backend OpenAI-compatibile può puntare a LM Studio in locale o a un
    servizio su Internet: senza questo controllo, il secondo caso veniva
    mostrato come "locale", cioè l'esatto contrario della realtà."""
    name = type(llm).__name__
    if name == "ClaudeCodeBackend":
        return "claude"
    if name == "OpenAICompatBackend":
        from app.llm.availability import e_locale
        return "local" if e_locale(getattr(llm, "base_url", "")) else "cloud"
    return "local"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_index()  # auto-heal entity_index per DB pre-feature
    init_rep_db()   # crea reputation.db (feed abuse.ch, DB separato)
    # SOLO SVILUPPO — DA RIMUOVERE prima di un uso reale: seed osservazioni
    # demo per test manuale rapido (POE_DEMO_DATA=1 in .env, opt-in, mai attivo
    # di default). No-op se il DB ha già osservazioni (vedi app/demo_seed.py).
    if os.environ.get("POE_DEMO_DATA"):
        from app.demo_seed import seed_demo_data
        seed_demo_data()
    llm = _make_llm_backend()
    logger.info("LLM backend: %s (%s)", type(llm).__name__, llm.model_name)
    app.state.recognizer = Recognizer(RegexExtractor(), SpacyExtractor())
    app.state.llm_extractor = LLMExtractor(llm)
    app.state.llm_backend = llm
    app.state.enricher_registry = EnricherRegistry([IPEnricher(), WHOISEnricher(), ReputationEnricher()])
    logger.info("POE v0.5 starting — DB: %s", DB_PATH)

    # Warmup LLM in background: carica il modello in RAM al boot così il primo
    # expand di un IOC non paga i ~5-10s di load. Saltato sotto pytest (i test
    # sostituiscono il backend e non devono caricare il modello). Errori silenziati.
    import os as _os
    import asyncio as _asyncio
    if not _os.environ.get("PYTEST_CURRENT_TEST"):
        # Warmup del modello SOLO se POE_LLM_WARMUP è attivo. In modalità hub
        # (hub vocale centrale) OSINT NON deve prendere la VRAM al boot: gliela
        # cede l'hub via /admin/llm/*. Standalone: POE_LLM_WARMUP=1 per pre-caricare.
        if _os.environ.get("POE_LLM_WARMUP", "").strip().lower() in {"1", "true", "yes", "on"}:
            async def _warmup():
                try:
                    await llm.is_available()
                    logger.info("LLM warmup completato")
                except Exception:
                    logger.warning("LLM warmup fallito (modello caricato al primo uso)")
            app.state._warmup_task = _asyncio.create_task(_warmup())
        app.state._rep_task = _asyncio.create_task(refresh_stale(force=False))

    yield


app = FastAPI(
    title="POE — Personal Observation Engine",
    description=(
        "Threat-intelligence locale: estrazione deterministica di IOC, "
        "enrichment, correlazione e lookup live. LLM on-demand, mai nel "
        "percorso critico."
    ),
    version=__version__,
    lifespan=lifespan,
)
app.add_middleware(SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)
templates = Jinja2Templates(env=_jinja_env)

# Jinja2 globals per i template
templates.env.globals["region_to_label"] = _region_to_label
templates.env.globals["region_to_flag"] = _region_to_flag

_VALID_VIEWS = {"all", "kept", "draft"}
_VALID_LIMITS = (10, 30, 50, 100, 200)


def _build_synthesis_prompt(raw_input: str, entities: list[dict],
                             observation_id: int | None = None) -> tuple[str, str]:
    import yaml as _yaml
    from pathlib import Path as _Path
    p = _Path(__file__).parent / "llm" / "prompts" / "synthesis.yaml"
    tmpl = _yaml.safe_load(p.read_text(encoding="utf-8"))
    lines = []
    for e in entities[:30]:
        etype, evalue = e.get("type"), e.get("value")
        line = f"- [{etype}] {evalue} ({e.get('confidence')})"
        # Enrichment automatico (geo/whois) già in obs["entities"][i]["metadata"]:
        # prima veniva scartato, il LLM vedeva solo type/value/confidence e
        # concludeva "dati insufficienti" anche quando i dati c'erano.
        meta = e.get("metadata") or {}
        if meta:
            line += f"\n  enrichment: {json.dumps(meta, ensure_ascii=False, default=str)}"
        # Dati raw dei tool live già interrogati per questa entità (stessa
        # cache/etichettatura usata da _build_entity_ai_prompt).
        if observation_id is not None:
            live = _cached_live_results_for(observation_id, evalue)
            for rid, res in live.items():
                name = _RESOURCE_DISPLAY_NAMES.get(rid, rid)
                line += f"\n  {name}: {json.dumps(res, ensure_ascii=False, default=str)}"
        lines.append(line)
    user = tmpl["user"].replace("{raw_input}", raw_input[:500]).replace(
        "{entities}", "\n".join(lines) or "(nessuna entità)"
    )
    return user, tmpl["system"]


def _build_export_ai_prompt(report: str) -> tuple[str, str]:
    import yaml as _yaml
    from pathlib import Path as _Path
    p = _Path(__file__).parent / "llm" / "prompts" / "export_ai.yaml"
    tmpl = _yaml.safe_load(p.read_text(encoding="utf-8"))
    user = tmpl["user"].replace("{report}", report)
    return user, tmpl["system"]


def _format_synthesis(text: str) -> str:
    """Prosa LLM (markdown leggero) -> HTML sicuro: escape + grassetto, liste puntate,
    paragrafi. Solo tag interni (p/ul/li/strong/br). Usata dalla route E dal template
    (Jinja global) cosi' la sintesi e' formattata sia nello swap HTMX sia al reload."""
    import re
    if not text or not text.strip():
        return ""
    esc = html.escape(text.strip())
    esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
    parts: list[str] = []
    for blk in re.split(r"\n\s*\n", esc):
        lines = [ln.strip() for ln in blk.splitlines() if ln.strip()]
        if not lines:
            continue
        if all(re.match(r"^[-*•]\s+", ln) for ln in lines):
            items = "".join("<li>" + re.sub(r"^[-*•]\s+", "", ln) + "</li>" for ln in lines)
            parts.append("<ul>" + items + "</ul>")
        else:
            parts.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(parts)


def _render_synthesis(text: str, model: str) -> str:
    """HTML del pannello sintesi — STESSA struttura di detail.html (synthesis-panel-v5),
    cosi' lo swap HTMX outerHTML su #synthesis-panel resta coerente e ben posizionato."""
    return (
        '<section id="synthesis-panel" style="margin-top:var(--sp-xl);">'
        '<div class="synthesis-panel-v5">'
        '<div class="synthesis-header">'
        '<span class="synthesis-title">&#9656; Sintesi Intelligence</span>'
        f'<span class="synthesis-model">{html.escape(model)}</span>'
        '</div>'
        f'<div class="synthesis-body">{_format_synthesis(text)}</div>'
        '</div></section>'
    )


templates.env.globals["format_synthesis"] = _format_synthesis


def _llm_label() -> str:
    """Nome modello LLM reale per la UI (no 'poe:latest'/Ollama hardcoded)."""
    llm = getattr(app.state, "llm_backend", None)
    return (getattr(llm, "model_name", "") or "").split("/")[-1] or "LLM"


templates.env.globals["llm_label"] = _llm_label
templates.env.globals["resource_url"] = resource_url


# ── Validazione LLM degli IOC a bassa confidenza (background) ──
# spaCy a volte marca come person_name parole comuni ("Connessioni"): l'LLM,
# in background dopo /analyze, valuta le entità low e droppa i falsi positivi.
_LOW_VALIDATE_TYPES = {"person_name", "org_name", "address"}
_BG_TASKS: set = set()


async def _validate_low_entities(app: FastAPI, observation_id: int) -> None:
    """Best-effort: l'LLM droppa i FP tra le entità a bassa confidenza. Non solleva."""
    import json as _json
    try:
        obs = get_by_id(observation_id)
        if obs is None:
            return
        low = [e for e in obs.get("entities", [])
               if e.get("confidence") == "low" and e.get("type") in _LOW_VALIDATE_TYPES]
        if not low:
            return
        llm = getattr(app.state, "llm_backend", None)
        if llm is None or not await llm.is_available():
            return
        lines = "\n".join(f'- [{e["type"]}] {e["value"]}' for e in low)
        system = (
            "Sei un validatore OSINT. Ricevi entità a BASSA confidenza estratte "
            "automaticamente. Indica quali sono FALSI POSITIVI (parole comuni, "
            "frammenti, non vere entità del loro tipo). Rispondi SOLO con JSON: "
            '{"drop": ["valore", ...]} coi soli valori falsi positivi (lista vuota se nessuno).'
        )
        user = f"Entità da validare:\n{lines}\n\nJSON:"
        raw = (await llm.generate(user, system)).strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        drop = set(_json.loads(raw).get("drop", []))
        for e in low:
            if e["value"] in drop:
                remove_entity(observation_id, e["type"], e["value"])
        if drop:
            logger.info("validate-low obs=%s dropped=%d", observation_id, len(drop))
    except Exception:
        logger.exception("validate_low_entities failed obs=%s", observation_id)


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

def _reputation_feeds_status() -> dict:
    """Stato aggregato dei feed reputation, verificato in locale (nessuna
    chiamata di rete): online se tutti freschi entro il proprio ttl_hours,
    slow se alcuni stale, offline se mai scaricati (o in errore)."""
    try:
        feeds = load_feeds()
        known_sources = {row["source"] for row in feed_status()}
        if not known_sources:
            return {"name": "Reputation feeds", "state": "offline"}
        stale_count = sum(
            1 for f in feeds
            if f["name"] in known_sources and is_stale(f["name"], f["ttl_hours"])
        )
        if stale_count == 0:
            state = "online"
        elif stale_count < len(feeds):
            state = "slow"
        else:
            state = "offline"
        return {"name": "Reputation feeds", "state": state}
    except Exception:
        logger.exception("_reputation_feeds_status failed")
        return {"name": "Reputation feeds", "state": "offline"}


_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Strumenti automatici (nessuna chiave richiesta) mostrati nella pagina
# "Servizi & API" — stessi servizi della status bar, qui con descrizione
# estesa e IOC di competenza (assenti dalla status bar per spazio).
_SERVICE_TOOLS = [
    {"category": "Locale", "name": "LLM locale (MLX)", "ioc": "testo libero",
     "description": "Modello linguistico eseguito in locale (RAM del Mac): estrazione assistita e sintesi su richiesta. Nessun dato lascia il dispositivo."},
    {"category": "Locale", "name": "spaCy NER", "ioc": "nomi persona, organizzazioni",
     "description": "Riconoscimento di entità nominate, locale: individua nomi e organizzazioni durante l'estrazione automatica."},
    {"category": "Locale", "name": "Reputation feeds (abuse.ch)", "ioc": "IP, dominio, URL, hash",
     "description": "Feed locali ThreatFox/URLhaus/MalwareBazaar: segnala se un IOC è già noto come malevolo. Aggiornati periodicamente, freschezza verificata in locale."},
    {"category": "Rete & Whois", "name": "ip-api.com", "ioc": "IP",
     "description": "Geolocalizzazione IP (paese, città, ISP): arricchisce automaticamente ogni IP appena osservato."},
    {"category": "Rete & Whois", "name": "WHOIS / RDAP", "ioc": "dominio, IP",
     "description": "Anagrafica di registrazione: registrar e date di creazione/scadenza per i domini, organizzazione titolare per gli IP."},
    {"category": "Database pubblici", "name": "crt.sh", "ioc": "dominio",
     "description": "Log pubblici di Certificate Transparency: scopre sottodomini e infrastruttura correlata, senza mai contattare il dominio target."},
    {"category": "Database pubblici", "name": "urlscan.io", "ioc": "dominio, URL, IP",
     "description": "Scan storici pubblici: screenshot, richieste di rete e IP di hosting già osservati da altri operatori. Per un IP, i domini/URL che ha ospitato."},
    {"category": "Database pubblici", "name": "NVD (NIST)", "ioc": "CVE",
     "description": "Database ufficiale delle vulnerabilità: score CVSS, prodotti affetti, riferimenti a patch."},
    {"category": "Database pubblici", "name": "Team Cymru / BGP.HE.net", "ioc": "IP",
     "description": "ASN e prefisso di rete (CIDR) di un IP: a chi appartiene davvero l'infrastruttura, oltre alla geolocalizzazione."},
    {"category": "Database pubblici", "name": "RIPEstat", "ioc": "IP",
     "description": "Contatti abuse ufficiali di un blocco IP, per segnalare attività malevola al gestore della rete."},
    {"category": "Persone & Identità", "name": "Gravatar", "ioc": "email",
     "description": "Profilo pubblico associato a un'email (hash MD5): nome e account social collegati, solo dati resi pubblici dal titolare. Keyless."},
    {"category": "Persone & Identità", "name": "XposedOrNot", "ioc": "email",
     "description": "Data-breach pubblici in cui compare un'email (uso difensivo). Keyless."},
    {"category": "Persone & Identità", "name": "Dati numero (locale)", "ioc": "telefono",
     "description": "Validità, regione, operatore e tipo di linea di un numero — calcolo in locale (offline, nessuna chiamata di rete, nessun leak)."},
    {"category": "Persone & Identità", "name": "Link profili (GitHub/X/Instagram/Reddit/Telegram/Keybase)", "ioc": "username, social handle",
     "description": "Costruzione dei link ai profili pubblici sulle principali piattaforme per uno username — versione passiva e sicura dell'enumerazione (solo link, nessuna scansione attiva)."},
]

# Strumenti a chiave: senza key restano link esterni, con key POE lavora
# direttamente (vedi _KEY_GATED_RESOURCES): tutte e 3 hanno un consumer live.
_MANAGED_API_KEYS = {
    "ABUSEIPDB_API_KEY": {
        "name": "AbuseIPDB", "ioc": "IP", "status_url": "https://www.abuseipdb.com/",
        "description": "Segnalazioni comunitarie di abuso (spam, brute-force, scanning, C2) con un abuse-confidence-score. Con la chiave, POE mostra il risultato direttamente nella scheda IOC; senza, resta un link esterno.",
    },
    "VIRUSTOTAL_API_KEY": {
        "name": "VirusTotal", "ioc": "URL, hash", "status_url": "https://www.virustotal.com/",
        "description": "Verdetto aggregato di 70+ motori antivirus/sandbox: rilevazioni malevole/sospette, reputation, categorie. Con la chiave, POE mostra il risultato direttamente nella scheda IOC; senza, resta un link esterno.",
    },
    "SHODAN_API_KEY": {
        "name": "Shodan", "ioc": "IP", "status_url": "https://www.shodan.io/",
        "description": "Dispositivi e servizi esposti su Internet per IP: porte aperte, banner, organizzazione, vulnerabilità note (CVE). Chiave OPZIONALE: senza, POE usa già InternetDB (gratuito) e mostra porte/CVE/tag nella scheda IOC; con la chiave aggiunge i dati host più ricchi (org/ISP/OS) quando il piano lo consente.",
    },
    "ABUSECH_API_KEY": {
        "name": "abuse.ch (ThreatFox + URLhaus)", "ioc": "IP, dominio, URL, hash", "status_url": "https://auth.abuse.ch/",
        "description": "Una sola chiave GRATUITA abilita due lookup live: ThreatFox (attribuzione a famiglia malware di un IOC) e URLhaus (URL malevoli noti per host/URL). Genera la Auth-Key su auth.abuse.ch (registrazione gratuita) e incollala qui — dev'essere la Auth-Key del portale account, non una vecchia chiave. Senza chiave valida restano link esterni.",
    },
    "OTX_API_KEY": {
        "name": "AlienVault OTX", "ioc": "IP, dominio, URL, hash, CVE", "status_url": "https://otx.alienvault.com/",
        "description": "Chiave GRATUITA che copre TUTTI i tipi di IOC: pulse di threat-intel community (chi ha segnalato l'indicatore, famiglie malware, tag). Con la chiave, POE mostra il risultato nella scheda IOC.",
    },
    "HUNTER_API_KEY": {
        "name": "Hunter.io", "ioc": "email", "status_url": "https://hunter.io/",
        "description": "Chiave GRATUITA (25 verifiche/mese): recapitabilità di un'email (valida/rischiosa/non recapitabile), se è usa-e-getta o webmail, score. Con la chiave, POE mostra il risultato nella scheda IOC.",
    },
    "IPQS_API_KEY": {
        "name": "IPQualityScore", "ioc": "email, telefono", "status_url": "https://www.ipqualityscore.com/",
        "description": "Fraud score e reputazione per email e numeri di telefono: validità, usa-e-getta, abuso recente, se trapelata/rischioso. Chiave GRATUITA (free tier limitato). Con la chiave, POE mostra il risultato nella scheda IOC.",
    },
    "NUMVERIFY_API_KEY": {
        "name": "Numverify", "ioc": "telefono", "status_url": "https://numverify.com/",
        "description": "Validazione live di un numero di telefono: valido, paese, operatore, tipo linea (mobile/fisso/VoIP). Chiave GRATUITA (100 richieste/mese). Con la chiave, POE mostra il risultato nella scheda IOC.",
    },
}


_STATE_SORT_PRIORITY = {"offline": 0, "slow": 1, "online": 2}


_MOTORI_ETICHETTE = {
    "mlx": ("Locale — MLX", "Apple Silicon. I dati non escono dal dispositivo."),
    "ollama": ("Locale — Ollama", "Gira su qualunque hardware. I dati non escono dal dispositivo."),
    "openai": ("Server compatibile OpenAI", "LM Studio, llama.cpp, vLLM, OpenRouter, endpoint aziendale."),
    "claude": ("Claude", "Via abbonamento Claude Code, non l'API a consumo. I dati escono verso il cloud."),
}


def _render_motori_ai() -> str:
    """La scelta del motore AI, accanto alle chiavi.

    Prima si poteva cambiare solo il modello vocale dalla status bar, e Ollama —
    l'unico motore che gira su qualunque hardware — era raggiungibile soltanto
    modificando una variabile d'ambiente. Chi scaricava POE su un PC non-Apple
    non aveva modo di configurarlo dall'interfaccia.

    Ogni motore mostra **perche'** non e' disponibile, quando non lo e': un
    elenco di voci grigie senza spiegazione lascia l'utente a indovinare, ed e'
    esattamente il momento in cui abbandona."""
    from app.llm.availability import rileva

    attivo = (os.environ.get("POE_LLM_BACKEND", "") or "").strip().lower()
    d = getattr(app.state, "llm_disponibilita", None) or rileva()

    righe = []
    for chiave, (nome, nota) in _MOTORI_ETICHETTE.items():
        usabile = d.usabile(chiave)
        motivo = d.motivo(chiave)
        righe.append(
            '<label class="motore-row' + ('' if usabile else ' motore-off') + '">'
            f'<input type="radio" name="backend" value="{chiave}"'
            + (' checked' if chiave == attivo else '')
            + ('' if usabile else ' disabled')
            + '>'
            f'<span class="motore-nome">{html.escape(nome)}</span>'
            f'<span class="motore-nota">{html.escape(motivo or nota)}</span>'
            '</label>'
        )

    modello = html.escape(os.environ.get("POE_LLM_MODEL", ""), quote=True)
    return (
        '<div class="api-section-title">Motore AI</div>'
        '<form class="api-keys-form" hx-post="/admin/llm/backend" '
        'hx-target="#api-keys-panel-body" hx-swap="none">'
        + "".join(righe)
        + '<input type="text" name="model" class="label-input" '
          f'value="{modello}" placeholder="modello (vuoto = predefinito del motore)">'
        + '<button type="submit" class="api-keys-save">Applica</button>'
        + '<p class="api-keys-hint">La scelta viene salvata in .env e sopravvive al '
          'riavvio. L\'estrazione degli indicatori e\' deterministica e non usa '
          'l\'AI: senza motore POE funziona, si perdono solo sintesi e analisi.</p>'
        + '</form>'
    )


async def _render_api_keys_panel() -> str:
    """Corpo della pagina 'Servizi & API': elenco strumenti automatici (sola
    lettura) + chiavi gestite con il valore reale visibile. POE è locale
    mono-utente: chi apre questa pagina ha già accesso diretto a .env sul
    filesystem, quindi mascherare qui non aggiunge sicurezza reale. Le righe
    a chiave mostrano anche la reachability reale del sito (stesso pallino
    online/slow/offline della status bar, stessa cache) e vengono ordinate
    coi problemi/down per primi."""
    rows = []
    current_category = None
    for tool in _SERVICE_TOOLS:
        if tool["category"] != current_category:
            if current_category is not None:
                rows.append('</div>')
            current_category = tool["category"]
            rows.append(
                '<div class="api-tool-group">'
                f'<div class="source-category-title">&#9656; {html.escape(current_category)}</div>'
            )
        rows.append(
            '<div class="api-tool-row">'
            f'<div class="api-tool-name">{html.escape(tool["name"])}'
            f'<span class="api-tool-ioc">{html.escape(tool["ioc"])}</span></div>'
            f'<p class="api-tool-description">{html.escape(tool["description"])}</p>'
            '</div>'
        )
    if current_category is not None:
        rows.append('</div>')

    states = await asyncio.gather(*(
        site_reachability(info["status_url"]) for info in _MANAGED_API_KEYS.values()
    ))
    ranked = sorted(
        zip(_MANAGED_API_KEYS.items(), states),
        key=lambda pair: _STATE_SORT_PRIORITY.get(pair[1], 1),
    )

    key_rows = []
    for (key, info), state in ranked:
        current_value = os.environ.get(key, "")
        configured = bool(current_value)
        status = "configurata" if configured else "non configurata"
        status_cls = "api-key-status-on" if configured else "api-key-status-off"
        key_rows.append(
            '<div class="api-tool-row api-key-row">'
            f'<div class="api-tool-name"><span class="status-dot {html.escape(state)}" '
            f'title="{html.escape(state)}"></span>{html.escape(info["name"])}'
            f'<span class="api-tool-ioc">{html.escape(info["ioc"])}</span>'
            f'<span class="api-key-status {status_cls}">({status})</span></div>'
            f'<p class="api-tool-description">{html.escape(info["description"])}</p>'
            f'<label for="{html.escape(key)}" class="sr-only">{html.escape(info["name"])} API key</label>'
            '<div class="api-key-input-row">'
            f'<input type="text" id="{html.escape(key)}" name="{html.escape(key)}" '
            f'value="{html.escape(current_value)}" placeholder="incolla qui la key" autocomplete="off">'
            f'<button type="button" class="btn-raw api-key-test-btn" '
            f'hx-post="/api/settings/keys/test/{html.escape(key)}" '
            f'hx-include="#{html.escape(key)}" '
            f'hx-target="#{html.escape(key)}-test-result" hx-swap="innerHTML">Test</button>'
            f'<span id="{html.escape(key)}-test-result" class="api-key-test-result"></span>'
            '</div>'
            '</div>'
        )
    return (
        _render_motori_ai()
        + '<div class="api-section-title">Strumenti automatici</div>'
        '<div class="api-tools-list">' + "".join(rows) + '</div>'
        '<div class="api-section-title">Chiavi API</div>'
        '<form class="api-keys-form" hx-post="/api/settings/keys" '
        'hx-target="#api-keys-panel-body" hx-swap="innerHTML">'
        + "".join(key_rows)
        + '<button type="submit" class="api-keys-save">Salva</button>'
        + '<p class="api-keys-hint">Salvate in .env (mai committato), attive subito senza riavviare. Campo lasciato vuoto = chiave rimossa.</p>'
        + '</form>'
    )


@app.get("/settings/api", response_class=HTMLResponse)
async def settings_api_page(request: Request):
    return templates.TemplateResponse(
        request, "settings_api.html", {"panel_html": await _render_api_keys_panel()}
    )


@app.post("/api/settings/keys", response_class=HTMLResponse)
async def save_api_keys_route(request: Request):
    form = await request.form()
    # Il valore mostrato è sempre quello reale corrente: un campo inviato
    # vuoto è un'azione deliberata dell'utente (ha cancellato il testo), non
    # un campo "non toccato" — quindi ora rimuove la chiave. Le chiavi non
    # presenti nel form (POST parziale) restano intatte.
    submitted = {key: str(form.get(key, "")).strip() for key in _MANAGED_API_KEYS if key in form}
    if submitted:
        write_env_keys(_ENV_PATH, submitted)
        for key, value in submitted.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
    return HTMLResponse(await _render_api_keys_panel())


_KEY_TEST_FUNCS = {
    # Lambda, non riferimento diretto: risolve il nome nel modulo ad ogni
    # chiamata (stesso motivo di _LOOKUP_HANDLERS) — un riferimento diretto
    # catturato all'import ignorerebbe un monkeypatch.setattr in test.
    "ABUSEIPDB_API_KEY": lambda k: test_abuseipdb_key(k),
    "VIRUSTOTAL_API_KEY": lambda k: test_virustotal_key(k),
    "SHODAN_API_KEY": lambda k: test_shodan_key(k),
    "ABUSECH_API_KEY": lambda k: test_abusech_key(k),
    "OTX_API_KEY": lambda k: test_otx_key(k),
    "HUNTER_API_KEY": lambda k: test_hunter_key(k),
    "IPQS_API_KEY": lambda k: test_ipqs_key(k),
    "NUMVERIFY_API_KEY": lambda k: test_numverify_key(k),
}


@app.post("/api/settings/keys/test/{key_name}", response_class=HTMLResponse)
async def test_api_key_route(key_name: str, request: Request):
    """Verifica ON-DEMAND (mai automatica) che una key funzioni davvero —
    testa il valore CORRENTE del campo (hx-include), anche se non ancora
    salvato con 'Salva'. Una singola query esplicita al click, non un ping
    periodico: qui è accettabile consumare quota (è l'operatore a deciderlo)."""
    test_func = _KEY_TEST_FUNCS.get(key_name)
    if test_func is None:
        return HTMLResponse('<span class="api-key-test-fail">chiave sconosciuta</span>', status_code=400)
    form = await request.form()
    value = str(form.get(key_name, "")).strip()
    if not value:
        return HTMLResponse('<span class="api-key-test-fail">inserisci una chiave prima di testare</span>')
    result = await test_func(value)
    if result.get("ok"):
        return HTMLResponse(f'<span class="api-key-test-ok">&#10003; {html.escape(result.get("detail", "funziona"))}</span>')
    return HTMLResponse(f'<span class="api-key-test-fail">&#10007; {html.escape(result.get("error", "errore"))}</span>')


# Servizi a chiave: la status bar pinga il SITO pubblico (mai l'endpoint API,
# per non consumare quota a pagamento solo per un pallino di stato). id ->
# (nome, url pubblica) — url presa da _MANAGED_API_KEYS (unica fonte).
# Verifica reale della key: bottone Test in /settings/api.
_KEY_GATED_STATUS_SITES = {
    "abuseipdb":  ("AbuseIPDB", _MANAGED_API_KEYS["ABUSEIPDB_API_KEY"]["status_url"]),
    "virustotal": ("VirusTotal", _MANAGED_API_KEYS["VIRUSTOTAL_API_KEY"]["status_url"]),
    "shodan":     ("Shodan", _MANAGED_API_KEYS["SHODAN_API_KEY"]["status_url"]),
}


@app.get("/api/status")
async def api_status(request: Request):
    """Stato dei componenti per la status bar 'Servizi' — solo quelli con un
    segnale reale (niente voci sempre "online" senza un vero check). Leggero:
    NON forza il load del modello LLM (riporta se e' gia' caricato in RAM).
    I feed reputation verificano la freschezza in locale via reputation.db,
    senza rete. I servizi a chiave (AbuseIPDB/VirusTotal/Shodan) pingano
    invece il sito pubblico (site_reachability, cache-ato) — mai l'API, per
    non consumare quota."""
    llm = getattr(request.app.state, "llm_backend", None)
    model = (getattr(llm, "model_name", "") or "").split("/")[-1] or "n/d"

    key_gated_states = await asyncio.gather(*(
        site_reachability(url) for _, url in _KEY_GATED_STATUS_SITES.values()
    ))
    key_gated_status = {
        svc_key: {"name": name, "state": state}
        for (svc_key, (name, _url)), state in zip(_KEY_GATED_STATUS_SITES.items(), key_gated_states)
    }

    return {
        # Verde se il backend LLM esiste: il modello si carica LAZY (non pre-caricato,
        # per risparmiare VRAM), quindi "non ancora in RAM" è lo stato normale, non un
        # problema. Rosso solo se manca del tutto il backend.
        "llm":        {"name": model, "state": "online" if llm is not None else "offline",
                       "kind": _llm_kind(llm) if llm is not None else "local"},
        # Quali motori AI girano su QUESTA macchina, e perche' gli altri no.
        # Chi ha appena scaricato il progetto scopre da qui cosa gli manca,
        # invece di incontrare un errore al primo clic su una funzione AI.
        "motori":     _motori_disponibili(request),
        "reputation": _reputation_feeds_status(),
        **key_gated_status,
    }


def _motori_disponibili(request: Request) -> dict:
    """Disponibilita' dei motori AI, rilevata all'avvio. Non risonda a ogni
    chiamata: aprire un socket verso Ollama a ogni polling della status bar
    sarebbe lavoro sprecato."""
    d = getattr(request.app.state, "llm_disponibilita", None)
    if d is None:
        from app.llm.availability import rileva
        d = rileva()
        request.app.state.llm_disponibilita = d
    return d.as_dict()


@app.get("/api/tools")
def api_tools():
    """Inventario dei siti/tool del catalogo OSINT NON già mostrati inline nella
    status bar (quelli hanno monitoraggio live). Popola la voce 'Altro': vista
    rapida di TUTTO ciò che POE può interrogare, raggruppata per categoria."""
    from app.osint_catalog import load_catalog
    inline = {"site-abuseipdb", "site-virustotal-search", "site-shodan"}
    kind_label = {"website": "Siti", "google_dork": "Google dork", "cli_tool": "Tool locali"}
    groups: dict[str, list[str]] = {}
    for r in load_catalog():
        if r.get("id") in inline:
            continue
        groups.setdefault(kind_label.get(r.get("kind"), "Altro"), []).append(r.get("name") or r.get("id"))
    for names in groups.values():
        names.sort(key=str.lower)
    return {"count": sum(len(v) for v in groups.values()), "groups": groups}


@app.get("/history", response_class=HTMLResponse)
def history_partial(request: Request, view: str = Query(default="all"), limit: int = Query(default=_RECENT_LIST_LIMIT)):
    """Partial della sezione 'Osservazioni' per lo swap HTMX dei filtri
    (Tutte/Preferiti/Bozze) e del conteggio scorrevole — niente full reload,
    niente flash bianco."""
    if view not in _VALID_VIEWS:
        view = "all"
    if limit not in _VALID_LIMITS:
        limit = _RECENT_LIST_LIMIT
    recent = _enrich_recent(get_recent(limit=limit, filter_kept=view))
    return templates.TemplateResponse(
        request, "_history.html", {"recent": recent, "current_view": view, "current_limit": limit}
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request, view: str = Query(default="all"), limit: int = Query(default=_RECENT_LIST_LIMIT)):
    if view not in _VALID_VIEWS:
        view = "all"
    if limit not in _VALID_LIMITS:
        limit = _RECENT_LIST_LIMIT
    recent = _enrich_recent(get_recent(limit=limit, filter_kept=view))
    return templates.TemplateResponse(
        request, "index.html", {"recent": recent, "current_view": view, "current_limit": limit}
    )


@app.get("/database", response_class=HTMLResponse)
def database_page(request: Request, view: str = Query(default="all")):
    """Pagina 'Database': TUTTE le osservazioni (non il sottoinsieme
    scorrevole di 'Osservazioni' in home) — stessi filtri Tutte/Preferiti/
    Bozze. limit=-1: SQLite lo tratta come "nessun limite" (vedi storage.get_recent)."""
    if view not in _VALID_VIEWS:
        view = "all"
    recent = _enrich_recent(get_recent(limit=-1, filter_kept=view))
    return templates.TemplateResponse(
        request, "database.html", {"recent": recent, "current_view": view, "total": len(recent)}
    )


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_route(request: Request, text: str = Form(...)):
    text = text.strip()
    if not text:
        return HTMLResponse(
            '<div class="error-card"><p>Inserire del testo da osservare.</p></div>',
            status_code=400,
        )
    if len(text) > MAX_INPUT_CHARS:
        return HTMLResponse(
            f'<div class="error-card"><p>Input troppo lungo (max {MAX_INPUT_CHARS:,} caratteri).</p></div>',
            status_code=400,
        )

    try:
        # Estrazione deterministica (regex + spaCy). NIENTE LLM nel percorso
        # critico: "Osserva" deve essere istantaneo. org_name/address sono
        # estratti on-demand (vedi /e/{id}/extract-ai).
        entities = request.app.state.recognizer.recognize(text)

        # Disambiguazione social (regex, zero costo)
        enriched = []
        for e in entities:
            if e.type == "social_handle":
                from app.models import Entity as _E
                platform = disambiguate_platform(e.value, text)
                e = _E(
                    type=e.type, value=e.value, original=e.original,
                    confidence=e.confidence, derived_from=e.derived_from,
                    metadata={**e.metadata, "platform": platform},
                )
            enriched.append(e)
        all_entities = enriched

        # Enrichment info iniziali (geo batch + WHOIS RDAP) in parallelo: i dati
        # base compaiono già nella riga IOC senza dover espandere/cliccare.
        all_entities = await request.app.state.enricher_registry.enrich_all(all_entities)

        observation_id = save_observation(text, all_entities)
        save_enrichment(observation_id, {e.value: e.metadata for e in all_entities if e.metadata})
        logger.info("analyze obs_id=%s entities=%d", observation_id, len(all_entities))

        # Validazione FP a bassa confidenza con LLM, in BACKGROUND: non blocca
        # "Osserva". Saltata sotto pytest. Apri l'osservazione per vederla pulita.
        import os as _os
        import asyncio as _asyncio
        if not _os.environ.get("PYTEST_CURRENT_TEST"):
            _t = _asyncio.create_task(_validate_low_entities(request.app, observation_id))
            _BG_TASKS.add(_t)
            _t.add_done_callback(_BG_TASKS.discard)
    except Exception:
        logger.exception("recognize failed for input length=%d", len(text))
        return templates.TemplateResponse(
            request, "error.html", {"error": "Errore interno. Riprova."}, status_code=500
        )

    entity_dicts = [e.to_dict() for e in all_entities]
    pivot_counts = counts_for_values([e["value"] for e in entity_dicts])
    risk_by_value = {e["value"]: compute_risk(e, pivot_counts.get(e["value"], 0)) for e in entity_dicts}
    observation_risk = aggregate_observation_risk(list(risk_by_value.values()))
    catalog_resources = {e["value"]: resources_for_type(e["type"]) for e in entity_dicts}
    private_ip_info_by_value = {e["value"]: private_ip_info(e["value"]) for e in entity_dicts if e["type"] == "ipv4"}
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "grouped_entities": group_by_type(entity_dicts),
            "observation_id": observation_id,
            "total": len(all_entities),
            "score": compute_score(entity_dicts),
            "accuracy": compute_accuracy(entity_dicts),
            "kept": False,
            "label": None,
            "recent": _enrich_recent(get_recent(limit=_RECENT_LIST_LIMIT)),
            "current_view": "all",
            "pivot_counts": pivot_counts,
            "risk_by_value": risk_by_value,
            "observation_risk": observation_risk,
            "catalog_resources": catalog_resources,
            "live_resource_ids": _live_resource_ids(),
            "private_ip_info": private_ip_info_by_value,
        },
    )


@app.get("/e/{observation_id}", response_class=HTMLResponse)
def detail(request: Request, observation_id: int):
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    entity_dicts = obs["entities"]
    pivot_counts = counts_for_values([e["value"] for e in entity_dicts])
    risk_by_value = {e["value"]: compute_risk(e, pivot_counts.get(e["value"], 0)) for e in entity_dicts}
    observation_risk = aggregate_observation_risk(list(risk_by_value.values()))
    catalog_resources = {e["value"]: resources_for_type(e["type"]) for e in entity_dicts}
    private_ip_info_by_value = {e["value"]: private_ip_info(e["value"]) for e in entity_dicts if e["type"] == "ipv4"}
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "observation": obs,
            "grouped_entities": group_by_type(entity_dicts),
            "total": len(entity_dicts),
            "score": compute_score(entity_dicts),
            "accuracy": compute_accuracy(entity_dicts),
            "kept": obs.get("kept", False),
            "label": obs.get("label"),
            "pivot_counts": pivot_counts,
            "risk_by_value": risk_by_value,
            "observation_risk": observation_risk,
            "catalog_resources": catalog_resources,
            "live_resource_ids": _live_resource_ids(),
            "private_ip_info": private_ip_info_by_value,
        },
    )


@app.post("/e/{observation_id}/keep", response_class=HTMLResponse)
def toggle_kept_route(request: Request, observation_id: int, kept: int = Form(0)):
    if get_by_id(observation_id) is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    new_kept = bool(kept)
    set_kept(observation_id, new_kept)
    # Lo stato finale è quello appena impostato (SQLite locale, no race).
    return HTMLResponse(_render_kept_toggle(observation_id, new_kept))


@app.post("/e/{observation_id}/label", response_class=HTMLResponse)
def set_label_route(request: Request, observation_id: int, label: str = Form("", max_length=200)):
    if get_by_id(observation_id) is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    set_label(observation_id, label)
    # set_label normalizza con strip() e None per stringa vuota: replichiamo
    # la stessa logica qui invece di fare una seconda query.
    saved_label = label.strip() if label and label.strip() else None
    return HTMLResponse(_render_label_area(observation_id, saved_label))


@app.post("/e/{observation_id}/remove-entity", response_class=HTMLResponse)
def remove_entity_route(
    observation_id: int,
    entity_type: str = Form(..., max_length=100),
    entity_value: str = Form(..., max_length=500),
):
    if get_by_id(observation_id) is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    remove_entity(observation_id, entity_type, entity_value)
    return HTMLResponse("")  # hx-swap="delete" rimuove il <li> dal DOM


@app.delete("/e/{observation_id}", response_class=HTMLResponse)
def delete_observation_route(request: Request, observation_id: int):
    if get_by_id(observation_id) is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    delete_observation(observation_id)
    recent = _enrich_recent(get_recent(limit=_RECENT_LIST_LIMIT))
    oob = (
        '<section id="history" class="history" '
        'aria-labelledby="history-heading" hx-swap-oob="true">'
    )
    history_html = templates.get_template("_history.html").render(
        {"recent": recent, "current_view": "all"}
    )
    return HTMLResponse(oob + history_html + "</section>")


def _observation_report_context(observation_id: int, obs: dict) -> tuple[dict, dict, dict, dict]:
    """Calcola risk_by_value/observation_risk/pivot_info/live_results_by_value per
    un'osservazione — stesso pattern usato da analyze_route/detail/extract_ai_route.
    live_results_by_value usa la stessa cache ed etichettatura per nome fonte
    già usate per il prompt LLM (vedi _cached_live_results_for), così il file
    scaricato dall'utente e il prompt del LLM vedono esattamente gli stessi dati raw."""
    entity_dicts = obs["entities"]
    pivot_counts = counts_for_values([e["value"] for e in entity_dicts])
    risk_by_value = {e["value"]: compute_risk(e, pivot_counts.get(e["value"], 0)) for e in entity_dicts}
    observation_risk = aggregate_observation_risk(list(risk_by_value.values()))
    pivot_info = {
        e["value"]: {
            "count": pivot_counts.get(e["value"], 0),
            "other_observation_ids": [
                o["id"] for o in observations_with_value(e["value"]) if o["id"] != observation_id
            ],
        }
        for e in entity_dicts
    }
    live_results_by_value = {
        e["value"]: {
            _RESOURCE_DISPLAY_NAMES.get(rid, rid): res
            for rid, res in _cached_live_results_for(observation_id, e["value"]).items()
        }
        for e in entity_dicts
    }
    live_results_by_value = {k: v for k, v in live_results_by_value.items() if v}
    return risk_by_value, observation_risk, pivot_info, live_results_by_value


@app.get("/e/{observation_id}/export.md")
def export_markdown(observation_id: int):
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    risk_by_value, observation_risk, pivot_info, live_results_by_value = _observation_report_context(observation_id, obs)
    content = build_markdown_report(obs, risk_by_value, observation_risk, pivot_info, live_results_by_value)
    return PlainTextResponse(
        content,
        headers={
            "Content-Disposition": f'attachment; filename="poe-{observation_id}.md"',
            "Content-Type": "text/plain; charset=utf-8",
        },
    )


@app.get("/e/{observation_id}/export.json")
def export_json_route(observation_id: int):
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    risk_by_value, observation_risk, pivot_info, live_results_by_value = _observation_report_context(observation_id, obs)
    report = build_json_report(obs, risk_by_value, observation_risk, pivot_info, live_results_by_value)
    return JSONResponse(
        report,
        headers={"Content-Disposition": f'attachment; filename="poe-{observation_id}.json"'},
    )


@app.get("/e/{observation_id}/export-ai.pdf")
async def export_pdf_ai(request: Request, observation_id: int):
    """Export PDF ben formattato con analisi investigativa LLM on-demand in
    coda. Riusa build_markdown_report (dati raw) solo per costruire il prompt
    dell'analisi AI — la resa visuale è build_pdf_report (reportlab), leggibile
    invece di JSON grezzo (quello resta nel .md). LLM non disponibile/errore ->
    PDF comunque scaricabile, con nota invece dell'analisi (mai un download rotto)."""
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    risk_by_value, observation_risk, pivot_info, live_results_by_value = _observation_report_context(observation_id, obs)
    raw_report = build_markdown_report(obs, risk_by_value, observation_risk, pivot_info, live_results_by_value)

    llm = request.app.state.llm_backend
    analysis = None
    if await llm.is_available():
        user_p, sys_p = _build_export_ai_prompt(raw_report)
        try:
            analysis = await llm.generate(user_p, sys_p)
        except Exception:
            logger.exception("export-ai failed obs_id=%s", observation_id)
            analysis = None

    pdf_bytes = build_pdf_report(
        obs, risk_by_value, observation_risk, pivot_info, live_results_by_value,
        analysis_text=analysis, analysis_model=llm.model_name if analysis else None,
    )
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="poe-{observation_id}-ai.pdf"'},
    )


@app.get("/e/cross/{entity_value:path}", response_class=HTMLResponse)
def cross_observation_route(request: Request, entity_value: str):
    if len(entity_value) > 500:
        raise HTTPException(status_code=400, detail="entity_value too long")
    observations = observations_with_value(entity_value)
    related = related_entities(entity_value)
    return templates.TemplateResponse(
        request,
        "cross_observation.html",
        {
            "entity_value": entity_value,
            "observations": observations,
            "count": len(observations),
            "related": related,
        },
    )


# Cache in-memory dell'analisi AI per-entità: evita di rigenerare a ogni expand.
# Chiave (observation_id, type, value). Non persistito (si azzera al riavvio).
_ENTITY_AI_CACHE: dict = {}

# Cache in-memory dei risultati RAW dei lookup live (AbuseIPDB/VirusTotal/Shodan/
# crt.sh/NVD/Cymru/urlscan...). I lookup sono fetchati dal browser via fetch()
# (nessuna persistenza server-side); qui li teniamo per-processo così che
# /entity-ai possa passarli al LLM se sono già stati interrogati per la stessa
# entità/osservazione — l'analisi AI deve vedere i dati grezzi dei tool, non
# solo l'enrichment automatico. Chiave (observation_id, resource_id, entity_value).
_LIVE_LOOKUP_CACHE: dict = {}


def _cached_live_results_for(observation_id: int, entity_value: str) -> dict:
    """Tutti i risultati RAW dei lookup per questa entità in questa osservazione,
    indicizzati per resource_id del catalogo.

    Legge dal DB, non più solo da un dict in RAM. Il dict viveva quanto il
    processo, e l'effetto si notava solo usando POE davvero: la sintesi
    investigativa è un bottone indipendente dall'espansione delle card, quindi
    chi la lanciava per prima — il modo normale di usarla — otteneva un'analisi
    che non aveva visto nessun dato live. Stessa cosa per gli export dopo un
    riavvio, e per i lookup on-demand lanciati dopo la generazione dell'analisi.

    La cache in RAM resta come primo livello e ha la precedenza: contiene i
    risultati appena ottenuti, che sono i più freschi."""
    salvati = get_lookup_results(observation_id, entity_value).get(entity_value, {})
    in_ram = {
        resource_id: result
        for (oid, resource_id, value), result in _LIVE_LOOKUP_CACHE.items()
        if oid == observation_id and value == entity_value
    }
    return {**salvati, **in_ram}


def _find_entity_meta(obs: dict, etype: str, evalue: str) -> dict:
    for e in obs.get("entities", []):
        if e.get("type") == etype and e.get("value") == evalue:
            return e.get("metadata") or {}
    return {}


# Nome leggibile per resource_id del catalogo (es. "site-abuseipdb" ->
# "AbuseIPDB"), stessa fonte di verità usata dai renderer delle schede — così
# il prompt LLM etichetta ogni blocco raw con un nome riconoscibile invece
# dell'id interno, e resta automaticamente in sync se il catalogo cambia.
_RESOURCE_DISPLAY_NAMES: dict[str, str] = {r["id"]: r["name"] for r in load_catalog()}


def _build_entity_ai_prompt(etype: str, evalue: str, meta: dict, raw: str,
                             live_results: dict | None = None) -> tuple[str, str]:
    # Dati noti passati GREZZI (JSON, non riassunti/filtrati): il LLM deve
    # vedere tutte le info che POE ha sull'entità, non un sottoinsieme curato.
    meta_json = json.dumps(meta, ensure_ascii=False, default=str) if meta else "nessuno oltre al valore"
    system = (
        "Sei un analista OSINT. In 1-2 frasi, italiano, professionale e fattuale, commenta "
        "questa singola entità nel contesto. Non inventare dati non presenti; se non c'è nulla "
        "di rilevante, dillo. Niente preamboli, niente persona.\n"
        "Riceverai dati grezzi (JSON) da più tool OSINT eterogenei, ciascuno con il proprio "
        "schema e la propria scala — non confondere campi di fonti diverse (es. un punteggio "
        "0-100 di una fonte non è comparabile a un conteggio di un'altra). Un campo assente o "
        "null significa 'dato non disponibile', non zero/negativo/pulito. Un blocco con "
        "\"ok\": false significa che quella fonte non ha risposto o non aveva la chiave "
        "configurata: NON trattarlo come 'nessuna minaccia trovata', semplicemente non hai "
        "quell'informazione. Cita solo ciò che è esplicitamente presente nei dati."
    )
    user = (f"Entità: [{etype}] {evalue}\n"
            f"Dati noti (raw): {meta_json}\n"
            f"Contesto (estratto): {raw[:300]}\n")
    # Dati RAW dei tool live già interrogati per questa entità (AbuseIPDB,
    # VirusTotal, Shodan, crt.sh, ecc.): passati grezzi, non riassunti, così
    # il LLM può leggere ed elaborare esattamente quello che vede l'utente
    # nella scheda IOC, non solo l'enrichment automatico. Ogni blocco è
    # etichettato col nome della fonte (non l'id interno del catalogo).
    if live_results:
        blocks = "\n".join(
            f"### {_RESOURCE_DISPLAY_NAMES.get(rid, rid)}\n"
            f"{json.dumps(res, ensure_ascii=False, default=str)}"
            for rid, res in live_results.items()
        )
        user += f"Dati raw da tool OSINT già interrogati:\n{blocks}\n"
    user += "Commento investigativo (1-2 frasi):"
    return user, system


def _render_entity_ai(text: str) -> str:
    return f'<div class="ai-text">{_format_synthesis(text)}</div>'


@app.post("/e/{observation_id}/entity-ai", response_class=HTMLResponse)
async def entity_ai_route(request: Request, observation_id: int,
                          entity_type: str = Form(..., max_length=100),
                          entity_value: str = Form(..., max_length=500)):
    """Analisi AI in prosa di una SINGOLA entità (lazy, al primo expand della card).
    Commento, non modifica dell'entità → coerente col principio 'LLM non tocca i dati'."""
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    key = (observation_id, entity_type, entity_value)
    if key in _ENTITY_AI_CACHE:
        return HTMLResponse(_render_entity_ai(_ENTITY_AI_CACHE[key]))
    llm = request.app.state.llm_backend
    if not await llm.is_available():
        return HTMLResponse('<div class="ai-text ai-error">Modello non disponibile.</div>', status_code=503)
    meta = _find_entity_meta(obs, entity_type, entity_value)
    live_results = _cached_live_results_for(observation_id, entity_value)
    user_p, sys_p = _build_entity_ai_prompt(
        entity_type, entity_value, meta, obs.get("raw_input", ""), live_results=live_results,
    )
    try:
        text = await llm.generate(user_p, sys_p)
    except Exception:
        logger.exception("entity-ai failed obs=%s %s=%s", observation_id, entity_type, entity_value)
        return HTMLResponse('<div class="ai-text ai-error">Errore generazione.</div>', status_code=500)
    _ENTITY_AI_CACHE[key] = text
    return HTMLResponse(_render_entity_ai(text))


@app.post("/e/{observation_id}/extract-ai", response_class=HTMLResponse)
async def extract_ai_route(request: Request, observation_id: int):
    """Estrazione LLM on-demand di org_name/address sull'osservazione.
    Fuori dal flusso veloce di /analyze. Ritorna il frammento entità aggiornato."""
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    llm = request.app.state.llm_backend
    if not await llm.is_available():
        return HTMLResponse('<p class="ai-error">Modello LLM non disponibile.</p>', status_code=503)
    try:
        new_ents = await request.app.state.llm_extractor.async_extract(obs.get("raw_input", ""))
    except Exception:
        logger.exception("extract-ai failed obs=%s", observation_id)
        return HTMLResponse('<p class="ai-error">Errore estrazione.</p>', status_code=500)
    add_entities(observation_id, new_ents)
    obs = get_by_id(observation_id)
    entity_dicts = obs["entities"]
    pivot_counts = counts_for_values([e["value"] for e in entity_dicts])
    risk_by_value = {e["value"]: compute_risk(e, pivot_counts.get(e["value"], 0)) for e in entity_dicts}
    observation_risk = aggregate_observation_risk(list(risk_by_value.values()))
    catalog_resources = {e["value"]: resources_for_type(e["type"]) for e in entity_dicts}
    private_ip_info_by_value = {e["value"]: private_ip_info(e["value"]) for e in entity_dicts if e["type"] == "ipv4"}
    # Fix 1: l'endpoint è condiviso dalla card fresca di /analyze (mai avuto
    # l'export) e dalla card di /e/{id} (dettaglio, che l'export ce l'ha).
    # HTMX manda sempre HX-Current-Url con l'URL della pagina che ha fatto la
    # richiesta: usiamolo per capire da dove arriva il click e non perdere il
    # bottone quando si passa per il dettaglio. Il guard su "/e/cross/" tiene
    # la vista pivot fuori (prefix diverso da /e/{id}, anche se qui non può
    # comunque triggerare extract-ai — meglio essere espliciti).
    current_url = request.headers.get("hx-current-url", "")
    is_detail_view = f"/e/{observation_id}" in current_url and "/e/cross/" not in current_url
    return templates.TemplateResponse(
        request, "results.html",
        {
            "grouped_entities": group_by_type(entity_dicts),
            "observation_id": observation_id,
            "total": len(entity_dicts),
            "score": compute_score(entity_dicts),
            "accuracy": compute_accuracy(entity_dicts),
            "kept": obs.get("kept", False),
            "label": obs.get("label"),
            "recent": _enrich_recent(get_recent(limit=_RECENT_LIST_LIMIT)),
            "current_view": "all",
            "pivot_counts": pivot_counts,
            "risk_by_value": risk_by_value,
            "observation_risk": observation_risk,
            "catalog_resources": catalog_resources,
            "live_resource_ids": _live_resource_ids(),
            "private_ip_info": private_ip_info_by_value,
            "show_export": is_detail_view,
        },
    )


@app.post("/e/{observation_id}/synthesis", response_class=HTMLResponse)
async def synthesis_route(request: Request, observation_id: int):
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")

    cached = get_synthesis(observation_id)
    if cached:
        return HTMLResponse(_render_synthesis(*cached))

    llm = request.app.state.llm_backend
    if not await llm.is_available():
        return HTMLResponse(
            '<section id="synthesis-panel"><div class="synthesis-card error">Modello LLM non disponibile.</div></section>',
            status_code=503,
        )

    user_p, sys_p = _build_synthesis_prompt(
        obs.get("raw_input", ""), obs.get("entities", []), observation_id=observation_id,
    )
    try:
        text = await llm.generate(user_p, sys_p)
    except Exception:
        logger.exception("synthesis failed obs_id=%s", observation_id)
        return HTMLResponse(
            '<section id="synthesis-panel"><div class="synthesis-card error">Errore generazione. Riprova.</div></section>',
            status_code=500,
        )

    save_synthesis(observation_id, text, llm.model_name)
    return HTMLResponse(_render_synthesis(text, llm.model_name))


@app.post("/e/{observation_id}/enrich/{entity_type}/{entity_value:path}", response_class=HTMLResponse)
async def enrich_entity_route(request: Request, observation_id: int, entity_type: str, entity_value: str):
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")

    from app.models import Entity as _Entity
    entities = []
    for e in obs.get("entities", []):
        try:
            entities.append(_Entity(
                type=e["type"], value=e["value"],
                original=e.get("original"), confidence=e.get("confidence", "medium"),
                metadata=e.get("metadata", {}), derived_from=e.get("derived_from"),
            ))
        except Exception:
            continue

    registry = request.app.state.enricher_registry
    enriched = await registry.enrich_on_demand(entity_type, entity_value, entities)

    cache = get_enrichment(observation_id)
    for e in enriched:
        if e.type == entity_type and e.value == entity_value:
            cache[e.value] = e.metadata
    save_enrichment(observation_id, cache)

    return HTMLResponse(
        f'<span class="enrich-ok">✓ {html.escape(entity_type)}: {html.escape(entity_value)}</span>'
    )


@app.post("/e/{observation_id}/lookup/{resource_id}/{entity_value:path}", response_class=HTMLResponse)
async def live_lookup_route(observation_id: int, resource_id: str, entity_value: str, rank: int = 0):
    """Interrogazione on-demand (click esplicito) verso risorse no-API-key del
    catalogo OSINT: crt.sh/urlscan.io (domain), urlscan.io (url), NVD (cve),
    Team Cymru whois (ipv4 -> ASN). Dispatch per resource_id (id del catalogo,
    non entity_type: un dominio ha 2 lookup disponibili). Nessuna persistenza:
    risultato ephemeral, ri-fetchato a ogni click. rank (query param opzionale)
    numera la risorsa nella stessa sequenza delle fonti automatiche."""
    if get_by_id(observation_id) is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")

    handler = _LOOKUP_HANDLERS.get(resource_id)
    if handler is None:
        return HTMLResponse('<span class="lookup-error">Risorsa non supportata.</span>', status_code=400)
    result = await handler(entity_value)
    _LIVE_LOOKUP_CACHE[(observation_id, resource_id, entity_value)] = result
    # Persistito: l'analisi AI e gli export devono poterlo vedere anche in una
    # sessione successiva, e la card non deve ri-colpire l'API per ridisegnare
    # un dato già ottenuto. Non solleva: se il salvataggio fallisce, l'utente
    # vede comunque il risultato che ha chiesto.
    save_lookup_result(observation_id, resource_id, entity_value, result)
    # L'analisi per-IOC già generata non ha visto questo lookup — tipicamente è
    # il caso dei lookup on-demand (WhatsMyName, Holehe), che partono da un click
    # successivo. Invalidarla fa sì che la prossima richiesta la rigeneri con il
    # dato nuovo, invece di restituire per sempre una versione parziale.
    # La chiave dell'analisi include il tipo di entità, che qui non abbiamo:
    # si tolgono tutte le voci per questo valore in questa osservazione.
    for k in [k for k in _ENTITY_AI_CACHE
              if k[0] == observation_id and k[-1] == entity_value]:
        _ENTITY_AI_CACHE.pop(k, None)
    return HTMLResponse(_LOOKUP_RENDERERS[resource_id](result, rank))


@app.post("/e/{observation_id}/refresh", response_class=HTMLResponse)
async def refresh_observation_route(request: Request, observation_id: int):
    """Ri-arricchisce tutte le entità di un'osservazione salvata (reputation/geo/WHOIS
    possono essere cambiati da quando è stata analizzata). Pivot/risk sono già sempre
    ricalcolati a ogni render — qui si aggiorna solo la metadata di enrichment, via
    la stessa cache già usata da enrich_entity_route (merge trasparente in get_by_id)."""
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")

    from app.models import Entity as _Entity
    entities = []
    for e in obs.get("entities", []):
        try:
            entities.append(_Entity(
                type=e["type"], value=e["value"],
                original=e.get("original"), confidence=e.get("confidence", "medium"),
                metadata=e.get("metadata", {}), derived_from=e.get("derived_from"),
            ))
        except Exception:
            continue

    registry = request.app.state.enricher_registry
    enriched = await registry.enrich_all(entities)

    cache = get_enrichment(observation_id)
    for e in enriched:
        cache[e.value] = e.metadata
    save_enrichment(observation_id, cache)

    obs = get_by_id(observation_id)
    entity_dicts = obs["entities"]
    pivot_counts = counts_for_values([e["value"] for e in entity_dicts])
    risk_by_value = {e["value"]: compute_risk(e, pivot_counts.get(e["value"], 0)) for e in entity_dicts}
    observation_risk = aggregate_observation_risk(list(risk_by_value.values()))
    catalog_resources = {e["value"]: resources_for_type(e["type"]) for e in entity_dicts}
    private_ip_info_by_value = {e["value"]: private_ip_info(e["value"]) for e in entity_dicts if e["type"] == "ipv4"}
    return templates.TemplateResponse(
        request, "results.html",
        {
            "grouped_entities": group_by_type(entity_dicts),
            "observation_id": observation_id,
            "total": len(entity_dicts),
            "score": compute_score(entity_dicts),
            "accuracy": compute_accuracy(entity_dicts),
            "kept": obs.get("kept", False),
            "label": obs.get("label"),
            "recent": _enrich_recent(get_recent(limit=_RECENT_LIST_LIMIT)),
            "current_view": "all",
            "pivot_counts": pivot_counts,
            "risk_by_value": risk_by_value,
            "observation_risk": observation_risk,
            "catalog_resources": catalog_resources,
            "live_resource_ids": _live_resource_ids(),
            "private_ip_info": private_ip_info_by_value,
            "show_export": True,
        },
    )


@app.post("/admin/reset", response_class=HTMLResponse)
def admin_reset_route():
    """Svuota TUTTO il DB — SOLO per testing. Ricarica la home via HX-Redirect."""
    reset_db()
    return HTMLResponse("", headers={"HX-Redirect": "/"})


@app.post("/admin/reputation/refresh", response_class=HTMLResponse)
async def admin_reputation_refresh():
    """Aggiorna i feed reputation in background (manuale)."""
    import asyncio as _asyncio
    _t = _asyncio.create_task(refresh_stale(force=True))
    _BG_TASKS.add(_t)                    # trattieni il riferimento: no GC mid-flight
    _t.add_done_callback(_BG_TASKS.discard)
    return HTMLResponse('<span class="feed-ok">Aggiornamento feed avviato…</span>')


@app.post("/admin/llm/unload")
async def admin_llm_unload():
    """Sfratta il modello LLM dalla VRAM (handoff con l'hub vocale: cede la VRAM).
    Reversibile — si ricarica lazy al prossimo uso. Endpoint locale, NON esposto via MCP."""
    backend = getattr(app.state, "llm_backend", None)
    if backend is None:
        return JSONResponse({"ok": False, "error": "nessun backend LLM"}, status_code=503)
    import asyncio as _asyncio
    await _asyncio.get_running_loop().run_in_executor(None, backend.unload)
    return JSONResponse({"ok": True, "unloaded": True})


@app.post("/admin/llm/warm")
async def admin_llm_warm():
    """Avvia il caricamento del modello LLM in VRAM in BACKGROUND e ritorna subito
    (non blocca il chiamante per i ~5-10s di load). Usato dall'hub quando entra
    in modalità OSINT: la VRAM è appena stata ceduta, OSINT la occupa caricando ora."""
    backend = getattr(app.state, "llm_backend", None)
    if backend is None:
        return JSONResponse({"ok": False, "error": "nessun backend LLM"}, status_code=503)
    import asyncio as _asyncio
    _t = _asyncio.create_task(backend.is_available())   # carica in background
    _BG_TASKS.add(_t)
    _t.add_done_callback(_BG_TASKS.discard)
    return JSONResponse({"ok": True, "warming": True})


_VALID_CLAUDE_MODELS = {"", "opus", "sonnet", "haiku"}


@app.post("/admin/llm/backend")
async def admin_llm_backend(backend: str = Form(...), model: str = Form("")):
    """Cambia a RUNTIME il backend LLM (Locale MLX <-> Claude via abbonamento)
    senza riavvio. Volatile: al riavvio torna a POE_LLM_BACKEND. Copre tutte le
    zone AI (usano app.state.llm_backend). Endpoint LOCALE, NON esposto via MCP."""
    kind = (backend or "").strip().lower()
    model = (model or "").strip().lower()
    # Ollama mancava, ed era proprio il motore che gira su qualunque hardware:
    # l'unico scegliibile solo modificando una variabile d'ambiente, cioe' non
    # scegliibile affatto per chi ha appena scaricato il progetto.
    if kind not in ("mlx", "ollama", "claude", "openai"):
        return JSONResponse({"ok": False, "error": "backend non valido"}, status_code=400)
    if kind == "claude" and model not in _VALID_CLAUDE_MODELS:
        return JSONResponse({"ok": False, "error": "modello Claude non valido"}, status_code=400)

    new = _build_backend(kind, model)
    # Claude: pre-check leggero (claude --version). Se non c'è, niente swap.
    if kind == "claude" and not await new.is_available():
        return JSONResponse(
            {"ok": False, "error": "Claude Code non disponibile (installa/accedi con l'abbonamento)"},
            status_code=400,
        )

    # Libera la VRAM del backend uscente (noop per Claude; MLX scarica il modello).
    old = getattr(app.state, "llm_backend", None)
    if old is not None and hasattr(old, "unload"):
        import asyncio as _asyncio
        try:
            await _asyncio.get_running_loop().run_in_executor(None, old.unload)
        except Exception:
            logger.warning("unload del backend uscente fallito (best-effort)")

    app.state.llm_backend = new
    app.state.llm_extractor = LLMExtractor(new)     # l'extractor avvolge il backend
    _ENTITY_AI_CACHE.clear()                         # analisi in cache erano del vecchio backend

    # La scelta sopravvive al riavvio. Prima era volatile: si sceglieva il
    # motore dalla UI e alla riaccensione si tornava al default, senza che
    # niente lo dicesse — impostare e dimenticare era impossibile.
    persistita = True
    try:
        write_env_keys(_ENV_PATH, {"POE_LLM_BACKEND": kind, "POE_LLM_MODEL": model})
        os.environ["POE_LLM_BACKEND"] = kind
        if model:
            os.environ["POE_LLM_MODEL"] = model
        else:
            os.environ.pop("POE_LLM_MODEL", None)
    except Exception:
        # Il file .env puo' essere in sola lettura (container, permessi): lo
        # swap vale comunque per questa sessione, ma va detto che non durera'.
        logger.warning("scelta del motore non persistita su .env", exc_info=True)
        persistita = False

    return JSONResponse({
        "ok": True, "backend": kind, "model": model,
        "name": new.model_name, "kind": _llm_kind(new),
        "persistita": persistita,
    })


@app.get("/health")
def health():
    ready = bool(getattr(app.state, "recognizer", None))
    return JSONResponse(
        {"status": "ok" if ready else "starting", "version": app.version},
        status_code=200 if ready else 503,
    )


class AnalyzeRequest(BaseModel):
    text: str
    # Entrambi opt-in: il contratto di default non cambia, perche' questo
    # endpoint ha gia' un chiamante — il connettore MCP — che vuole l'estrazione
    # pura, senza effetti collaterali e senza rete.
    save: bool = False      # lascia un'osservazione: la ricerca resta tracciata
    enrich: bool = False    # geo + WHOIS: senza, il chiamante riceve valori nudi
    lookups: bool = False   # reputazione e minacce: senza, "pulito" e' indistinguibile
                            # da "non ho guardato"


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest):
    """API JSON: testo -> entita' (riconoscimento DETERMINISTICO). Niente LLM.

    E' la via con cui l'hub vocale usa OSINT **dall'esterno**: fa la ricerca e
    riceve i dati da riportare in conversazione, senza aprire l'interfaccia.

    Con `save` l'osservazione resta in cronologia e ri-apribile — "tracciata nel
    modulo" significa poterci tornare sopra, non solo lasciare una riga di log.
    Con `enrich` le entita' portano geolocalizzazione e WHOIS: su un valore nudo
    non c'e' analisi possibile."""
    text = (req.text or "").strip()
    if not text:
        return JSONResponse({"error": "testo vuoto", "count": 0, "entities": []}, status_code=400)
    if len(text) > MAX_INPUT_CHARS:
        return JSONResponse({"error": "input troppo lungo", "count": 0, "entities": []}, status_code=400)
    recognizer = getattr(app.state, "recognizer", None)
    if recognizer is None:
        return JSONResponse({"error": "servizio non pronto", "count": 0, "entities": []}, status_code=503)

    entities = recognizer.recognize(text)

    if req.enrich and entities:
        registry = getattr(app.state, "enricher_registry", None)
        if registry is not None:
            try:
                entities = await registry.enrich_all(entities)
            except Exception:
                # La rete puo' mancare: meglio restituire le entita' senza
                # arricchimento che far fallire tutta la ricerca.
                logger.warning("api_analyze: arricchimento fallito", exc_info=True)

    observation_id = None
    if req.save:
        try:
            observation_id = save_observation(text, entities)
            meta = {e.value: e.metadata for e in entities if e.metadata}
            if meta:
                save_enrichment(observation_id, meta)
        except Exception:
            # Salvare e' un di piu': il chiamante riceve comunque la risposta.
            logger.warning("api_analyze: salvataggio fallito", exc_info=True)

    lookups: dict[str, dict] = {}
    if req.lookups and entities:
        lookups = await _run_lookups_for(entities, observation_id)

    dicts = [e.to_dict() for e in entities]
    return JSONResponse({"count": len(dicts), "entities": dicts,
                         "observation_id": observation_id, "lookups": lookups})


async def _run_lookups_for(entities, observation_id: int | None) -> dict[str, dict]:
    """Interroga le fonti live per ogni entita', come fa la UI espandendo le card.

    Senza questo, il percorso headless vedeva solo geolocalizzazione, WHOIS e il
    feed abuse.ch locale — mai reputazione e minacce, che stanno tutte qui. Un IP
    con 156 segnalazioni su AbuseIPDB risultava indistinguibile da uno pulito, e
    chi leggeva l'analisi ne concludeva che fosse innocuo.

    Le fonti girano in parallelo. Una che fallisce viene RIPORTATA come fallita,
    non omessa: "quella fonte non ha risposto" e' un'informazione diversa da
    "quella fonte non ha trovato nulla", e confonderle e' esattamente il modo in
    cui un'assenza si traveste da assoluzione."""
    disponibili = _live_resource_ids()

    async def una(valore: str, res_id: str):
        try:
            return res_id, await _LOOKUP_HANDLERS[res_id](valore)
        except Exception as exc:                        # noqa: BLE001
            logger.info("lookup %s su %s fallito: %s", res_id, valore, exc)
            return res_id, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    compiti, chiavi = [], []
    visti: set[tuple[str, str]] = set()
    for e in entities:
        for risorsa in resources_for_type(e.type):
            rid = risorsa.get("id")
            if rid not in disponibili or rid not in _LOOKUP_HANDLERS:
                continue
            if (e.value, rid) in visti:
                continue
            visti.add((e.value, rid))
            compiti.append(una(e.value, rid))
            chiavi.append(e.value)

    if not compiti:
        return {}

    out: dict[str, dict] = {}
    for valore, (rid, risultato) in zip(chiavi, await asyncio.gather(*compiti)):
        out.setdefault(valore, {})[rid] = risultato
        if observation_id is not None:
            # Persistiti come quelli della UI: l'analisi riportata in chat e
            # quella che si vede aprendo l'osservazione sono la stessa cosa.
            save_lookup_result(observation_id, rid, valore, risultato)
    return out


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _enrich_recent(recent: list[dict]) -> list[dict]:
    for item in recent:
        item["score"] = compute_score(item.get("entities", []))
        item["accuracy"] = compute_accuracy(item.get("entities", []))
    return recent


def _render_kept_toggle(observation_id: int, is_kept: bool) -> str:
    new_val = "0" if is_kept else "1"
    lbl = "&#9733; kept" if is_kept else "&#9734; draft"
    cls = "kept-btn kept-active" if is_kept else "kept-btn"
    pressed = "true" if is_kept else "false"
    aria = "Rimuovi da kept" if is_kept else "Marca come kept"
    return (
        f'<span id="kept-toggle-{observation_id}">'
        f'<form hx-post="/e/{observation_id}/keep" '
        f'hx-target="#kept-toggle-{observation_id}" hx-swap="outerHTML">'
        f'<input type="hidden" name="kept" value="{new_val}">'
        f'<button type="submit" class="{cls}" '
        f'aria-pressed="{pressed}" aria-label="{aria}">{lbl}</button>'
        f"</form></span>"
    )


def _render_lookup_source(
    name: str, pairs: list[tuple[str, object]], raw: dict,
    link: tuple[str, str] | None = None, rank: int = 0,
) -> str:
    """Vista formattata (kv-grid, espansa di default) + raw JSON on-demand
    (toggle .btn-raw già gestito globalmente da app.js, stesso pattern di
    source_block in _macros.html). link=(etichetta, url) opzionale: riga
    finale della kv-grid resa come <a> cliccabile invece che testo. rank>0
    mostra #N prima del nome, stesso markup di source_block (numerazione
    unica tra fonti automatiche e risorse esterne live)."""
    rows = "".join(
        f"<dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd>"
        for k, v in pairs if v not in (None, "", [])
    )
    if link and link[1]:
        label, href = link
        rows += (
            f"<dt>{html.escape(label)}</dt>"
            f'<dd><a href="{html.escape(href)}" target="_blank" rel="noopener noreferrer">{html.escape(href)}</a></dd>'
        )
    raw_json = html.escape(json.dumps(raw, indent=2, ensure_ascii=False, default=str))
    rank_span = f'<span class="source-rank">#{rank}</span>' if rank else ""
    # Niente div wrapper esterno .source-group: il chiamante (data-auto-lookup
    # nel template) è GIÀ quel wrapper, questo swap ne sostituisce solo il
    # contenuto (innerHTML). Un wrapper duplicato qui annidava .source-group
    # dentro .source-group ad ogni lookup live riuscito.
    return (
        '<div class="source-header">'
        f'<span class="source-name">{rank_span}{html.escape(name)}</span>'
        '<div class="source-meta"><span class="source-tag api">live</span>'
        '<button type="button" class="btn-raw">raw</button></div>'
        '</div>'
        '<div class="source-body">'
        f'<dl class="kv-grid">{rows}</dl>'
        f'<pre class="source-raw-data">{raw_json}</pre>'
        '</div>'
    )


def _render_lookup_error(name: str, error: str, rank: int = 0) -> str:
    """Stessa forma (header + body, niente wrapper) di _render_lookup_source,
    cosi l'errore sostituisce il contenuto del placeholder senza perdere il
    rank/nome nell'header. Include un bottone Riprova (gestito in app.js)."""
    rank_span = f'<span class="source-rank">#{rank}</span>' if rank else ""
    return (
        '<div class="source-header">'
        f'<span class="source-name">{rank_span}{html.escape(name)}</span>'
        '<div class="source-meta"><span class="source-tag api">errore</span></div>'
        '</div>'
        '<div class="source-body">'
        f'<span class="lookup-error">{html.escape(error)}</span> '
        '<button type="button" class="btn-raw btn-retry-lookup">Riprova</button>'
        '</div>'
    )


def _render_crtsh_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("crt.sh", result.get("error", "errore"), rank=rank)
    return _render_lookup_source("crt.sh", [
        ("certificati", result.get("cert_count")),
        ("ultimo issuer", result.get("latest_issuer")),
        ("sottodomini", ", ".join(result.get("subdomains", [])) or None),
    ], result, rank=rank)


def _render_nvd_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("NVD", result.get("error", "errore"), rank=rank)
    score = result.get("cvss_score")
    severity = result.get("cvss_severity") or ""
    score_str = f"{score} {severity}".strip() if score is not None else None
    published = result.get("published")
    return _render_lookup_source("NVD", [
        ("CVSS", score_str),
        ("pubblicata", published[:10] if published else None),
        ("descrizione", result.get("description")),
    ], result, rank=rank)


def _render_urlscan_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("urlscan.io", result.get("error", "errore"), rank=rank)
    scans = result.get("scans", [])
    latest = scans[0] if scans else {}
    return _render_lookup_source("urlscan.io", [
        ("scan trovati", result.get("total", len(scans))),
        ("ultimo IP hosting", latest.get("ip")),
        ("ultimo ASN", latest.get("asn")),
        ("ultima scansione", (latest.get("date") or "")[:10] or None),
    ], result, link=("report completo", latest.get("result_url")), rank=rank)


def _render_cymru_result(result: dict, rank: int = 0) -> str:
    # Nome mostrato = quello del catalogo ("BGP.HE.net (Hurricane Electric)",
    # vedi site-bgp-he-net in osint_catalog.yaml). Il dato arriva via whois di
    # Team Cymru (nessun endpoint HTTP reale esiste per bgp.he.net), ma
    # l'identità visibile all'utente deve restare coerente con l'header del
    # placeholder — prima si chiamava "Team Cymru (ASN)" e il cambio nome a
    # lookup completato faceva sembrare che BGP.HE.net fosse "sparito".
    name = "BGP.HE.net (Hurricane Electric)"
    if not result.get("ok"):
        return _render_lookup_error(name, result.get("error", "errore"), rank=rank)
    return _render_lookup_source(name, [
        ("ASN", result.get("asn")),
        ("AS name", result.get("as_name")),
        ("paese", result.get("country")),
        ("BGP prefix", result.get("bgp_prefix")),
        ("registry", result.get("registry")),
        ("allocato", result.get("allocated")),
        ("nota", result.get("note")),
    ], result, rank=rank)


def _render_abuseipdb_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("AbuseIPDB", result.get("error", "errore"), rank=rank)
    score = result.get("abuse_score")
    whitelisted = result.get("is_whitelisted")
    last_reported = result.get("last_reported")
    is_tor = result.get("is_tor")
    return _render_lookup_source("AbuseIPDB", [
        ("abuse score", f"{score}/100" if score is not None else None),
        ("tipo uso", result.get("usage_type")),
        ("segnalazioni", result.get("total_reports")),
        ("segnalatori distinti", result.get("num_distinct_users")),
        ("whitelisted", ("sì" if whitelisted else "no") if whitelisted is not None else None),
        ("Tor", ("sì" if is_tor else "no") if is_tor is not None else None),
        ("paese", result.get("country")),
        ("ISP", result.get("isp")),
        ("dominio", result.get("domain")),
        ("ultima segnalazione", last_reported[:10] if last_reported else None),
    ], result, rank=rank)


def _render_virustotal_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("VirusTotal", result.get("error", "errore"), rank=rank)
    if result.get("found") is False:
        return _render_lookup_source("VirusTotal", [
            ("stato", "non presente su VirusTotal (mai analizzato)"),
        ], result, rank=rank)
    malicious = result.get("malicious")
    suspicious = result.get("suspicious")
    total = sum(
        v for v in (malicious, suspicious, result.get("harmless"), result.get("undetected"))
        if isinstance(v, int)
    ) or None
    last_analysis = result.get("last_analysis_date")
    creation_date = result.get("creation_date")
    return _render_lookup_source("VirusTotal", [
        ("verdetto", f"{malicious}/{total} motori" if malicious is not None and total else None),
        ("famiglia", result.get("threat_label")),
        ("sospetti", suspicious),
        ("reputation", result.get("reputation")),
        ("nome", result.get("meaningful_name")),
        ("tipo", result.get("type_description")),
        ("categorie", result.get("categories")),
        ("tag", result.get("tags")),
        ("minacce (URL)", result.get("threat_names")),
        ("titolo (URL)", result.get("title")),
        ("URL finale", result.get("last_final_url")),
        ("AS owner", result.get("as_owner")),
        ("ASN", result.get("asn")),
        ("paese", result.get("country")),
        ("registrar", result.get("registrar")),
        ("creato il", creation_date[:10] if creation_date else None),
        ("record DNS", result.get("last_dns_records")),
        ("invii", result.get("times_submitted")),
        ("ultima analisi", last_analysis[:10] if last_analysis else None),
    ], result, rank=rank)


def _render_shodan_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Shodan", result.get("error", "errore"), rank=rank)
    ports = result.get("ports") or []
    vulns = result.get("vulns") or []
    return _render_lookup_source("Shodan", [
        ("porte aperte", ", ".join(str(p) for p in ports) or None),
        ("prodotti", ", ".join(result.get("products") or []) or None),
        ("tag", ", ".join(result.get("tags") or []) or None),
        ("org", result.get("org")),
        ("ISP", result.get("isp")),
        ("OS", result.get("os")),
        ("hostnames", ", ".join(result.get("hostnames") or []) or None),
        ("vulnerabilità (CVE)", ", ".join(vulns) or None),
    ], result, rank=rank)


def _render_gravatar_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Gravatar", result.get("error", "errore"), rank=rank)
    if not result.get("has_profile"):
        return _render_lookup_source("Gravatar", [
            ("profilo pubblico", "nessuno per questa email"),
        ], result, rank=rank)
    return _render_lookup_source("Gravatar", [
        ("nome", result.get("display_name")),
        ("account collegati", result.get("accounts")),
        ("posizione", result.get("location")),
    ], result, rank=rank)


def _render_xposedornot_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("XposedOrNot", result.get("error", "errore"), rank=rank)
    breached = result.get("breached")
    return _render_lookup_source("XposedOrNot", [
        ("compromessa", ("sì" if breached else "no") if breached is not None else None),
        ("numero breach", result.get("breach_count")),
        ("breach", result.get("breaches")),
    ], result, rank=rank)


def _render_phone_info_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Numero telefono", result.get("error", "errore"), rank=rank)
    valid = result.get("valid")
    return _render_lookup_source("Numero telefono", [
        ("valido", ("sì" if valid else "no") if valid is not None else None),
        ("prefisso paese", result.get("country_code")),
        ("regione", result.get("region")),
        ("operatore", result.get("carrier")),
        ("tipo linea", result.get("line_type")),
    ], result, rank=rank)


def _render_threatfox_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("ThreatFox", result.get("error", "errore"), rank=rank)
    if not result.get("found"):
        return _render_lookup_source("ThreatFox", [
            ("match", "nessun IOC noto in ThreatFox"),
        ], result, rank=rank)
    conf = result.get("confidence")
    fs = result.get("first_seen")
    return _render_lookup_source("ThreatFox", [
        ("malware", result.get("malware")),
        ("tipo minaccia", result.get("threat_type")),
        ("confidenza", f"{conf}%" if conf is not None else None),
        ("primo avvistamento", fs[:10] if fs else None),
        ("tag", result.get("tags")),
    ], result, rank=rank)


def _render_urlhaus_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("URLhaus", result.get("error", "errore"), rank=rank)
    if not result.get("found"):
        return _render_lookup_source("URLhaus", [
            ("match", "nessuna URL malevola nota"),
        ], result, rank=rank)
    return _render_lookup_source("URLhaus", [
        ("minaccia", result.get("threat")),
        ("stato URL", result.get("status")),
        ("URL malevole", result.get("url_count")),
        ("tag", result.get("tags")),
        ("blacklist", result.get("blacklists")),
    ], result, rank=rank)


def _render_otx_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("AlienVault OTX", result.get("error", "errore"), rank=rank)
    return _render_lookup_source("AlienVault OTX", [
        ("pulse (segnalazioni)", result.get("pulse_count")),
        ("nomi pulse", result.get("pulses")),
        ("famiglie malware", result.get("malware_families")),
        ("tag", result.get("tags")),
    ], result, rank=rank)


def _render_hunter_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Hunter (email)", result.get("error", "errore"), rank=rank)
    disposable = result.get("disposable")
    webmail = result.get("webmail")
    score = result.get("score")
    return _render_lookup_source("Hunter (email)", [
        ("recapitabilità", result.get("status")),
        ("risultato", result.get("result")),
        ("score", f"{score}/100" if score is not None else None),
        ("usa-e-getta", ("sì" if disposable else "no") if disposable is not None else None),
        ("webmail", ("sì" if webmail else "no") if webmail is not None else None),
    ], result, rank=rank)


def _render_cf_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Codice Fiscale", result.get("error", "errore"), rank=rank)
    valido = result.get("valido")
    return _render_lookup_source("Codice Fiscale (locale)", [
        ("carattere di controllo", ("valido" if valido else "NON valido") if valido is not None else None),
        ("sesso", result.get("sesso")),
        ("data di nascita", result.get("data_nascita")),
        ("comune di nascita", result.get("comune")),
        ("codice catastale", result.get("codice_catastale")),
    ], result, rank=rank)


def _render_dorks_result(result: dict, rank: int = 0) -> str:
    """Lista di Google Dork come link cliccabili (non kv-grid: ogni dork è un
    <a> verso la ricerca Google già pronta)."""
    if not result.get("ok"):
        return _render_lookup_error("Google Dork", result.get("error", "errore"), rank=rank)
    rows = "".join(
        f"<dt>{html.escape(d['label'])}</dt>"
        f'<dd><a href="{html.escape(d["url"])}" target="_blank" rel="noopener noreferrer">'
        f"{html.escape(d['query'])}</a></dd>"
        for d in result.get("dorks", [])
    )
    raw_json = html.escape(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    rank_span = f'<span class="source-rank">#{rank}</span>' if rank else ""
    return (
        '<div class="source-header">'
        f'<span class="source-name">{rank_span}Google Dork (ricerca mirata)</span>'
        '<div class="source-meta"><span class="source-tag api">live</span>'
        '<button type="button" class="btn-raw">raw</button></div>'
        '</div>'
        '<div class="source-body">'
        f'<dl class="kv-grid link-bundle-grid">{rows}</dl>'
        f'<pre class="source-raw-data">{raw_json}</pre>'
        '</div>'
    )


def _render_emailrep_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("EmailRep", result.get("error", "errore"), rank=rank)
    return _render_lookup_source("EmailRep (reputation email)", [
        ("reputazione", result.get("reputation")),
        ("sospetta", result.get("suspicious")),
        ("riferimenti", result.get("references")),
        ("credenziali trapelate", result.get("credentials_leaked")),
        ("in data-breach", result.get("data_breach")),
        ("attività malevola", result.get("malicious_activity")),
        ("profili social", result.get("profiles")),
        ("usa-e-getta", result.get("disposable")),
        ("provider gratuito", result.get("free_provider")),
        ("recapitabile", result.get("deliverable")),
        ("ultima attività", result.get("last_seen")),
    ], result, rank=rank)


def _render_hudsonrock_email_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Hudson Rock", result.get("error", "errore"), rank=rank)
    return _render_lookup_source("Hudson Rock (infostealer)", [
        ("compromessa", result.get("compromised")),
        ("infezioni", result.get("stealer_count")),
        ("dettaglio", result.get("stealers")),
        ("nota", result.get("message")),
    ], result, rank=rank)


def _render_hudsonrock_username_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Hudson Rock", result.get("error", "errore"), rank=rank)
    return _render_lookup_source("Hudson Rock (infostealer, username)", [
        ("compromesso", result.get("compromised")),
        ("infezioni", result.get("stealer_count")),
        ("dettaglio", result.get("stealers")),
        ("nota", result.get("message")),
    ], result, rank=rank)


def _render_github_api_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("GitHub", result.get("error", "errore"), rank=rank)
    if not result.get("found"):
        return _render_lookup_source("GitHub (profilo)", [("profilo", "nessun utente con questo username")], result, rank=rank)
    return _render_lookup_source("GitHub (profilo)", [
        ("nome", result.get("name")), ("azienda", result.get("company")),
        ("bio", result.get("bio")), ("località", result.get("location")),
        ("email pubblica", result.get("email")), ("twitter", result.get("twitter")),
        ("blog", result.get("blog")), ("repo pubblici", result.get("public_repos")),
        ("follower", result.get("followers")), ("iscritto dal", result.get("created_at")),
    ], result, link=("profilo", result.get("profile_url")), rank=rank)


def _render_keybase_api_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Keybase", result.get("error", "errore"), rank=rank)
    if not result.get("found"):
        return _render_lookup_source("Keybase (identità)", [("profilo", "nessun utente Keybase")], result, rank=rank)
    return _render_lookup_source("Keybase (identità)", [
        ("nome", result.get("full_name")), ("località", result.get("location")),
        ("account collegati", result.get("accounts")), ("chiavi PGP", result.get("pgp_keys")),
    ], result, link=("profilo", result.get("profile_url")), rank=rank)


def _render_gitlab_api_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("GitLab", result.get("error", "errore"), rank=rank)
    if not result.get("found"):
        return _render_lookup_source("GitLab (profilo)", [("profilo", "nessun utente GitLab")], result, rank=rank)
    return _render_lookup_source("GitLab (profilo)", [
        ("nome", result.get("name")), ("stato", result.get("state")),
        ("bio", result.get("bio")), ("località", result.get("location")),
        ("sito", result.get("website")), ("twitter", result.get("twitter")),
        ("linkedin", result.get("linkedin")), ("iscritto dal", result.get("created_at")),
    ], result, link=("profilo", result.get("profile_url")), rank=rank)


def _render_reddit_api_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Reddit", result.get("error", "errore"), rank=rank)
    if not result.get("found"):
        return _render_lookup_source("Reddit (account)", [("profilo", "nessun utente Reddit (o privato)")], result, rank=rank)
    return _render_lookup_source("Reddit (account)", [
        ("iscritto dal", result.get("created")),
        ("karma post", result.get("link_karma")),
        ("karma commenti", result.get("comment_karma")),
        ("verificato", result.get("verified")),
        ("moderatore", result.get("is_mod")),
    ], result, link=("profilo", result.get("profile_url")), rank=rank)


def _render_ipqs_email_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("IPQualityScore", result.get("error", "errore"), rank=rank)
    return _render_lookup_source("IPQualityScore (fraud score email)", [
        ("valida", result.get("valid")),
        ("usa-e-getta", result.get("disposable")),
        ("recapitabilità", result.get("deliverability")),
        ("fraud score", result.get("fraud_score")),
        ("abuso recente", result.get("recent_abuse")),
        ("trapelata", result.get("leaked")),
        ("prima vista", result.get("first_seen")),
    ], result, rank=rank)


def _render_ipqs_phone_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("IPQualityScore", result.get("error", "errore"), rank=rank)
    return _render_lookup_source("IPQualityScore (fraud score telefono)", [
        ("valido", result.get("valid")),
        ("attivo", result.get("active")),
        ("tipo linea", result.get("line_type")),
        ("operatore", result.get("carrier")),
        ("fraud score", result.get("fraud_score")),
        ("abuso recente", result.get("recent_abuse")),
        ("trapelato", result.get("leaked")),
        ("rischioso", result.get("risky")),
    ], result, rank=rank)


def _render_numverify_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Numverify", result.get("error", "errore"), rank=rank)
    return _render_lookup_source("Numverify (validazione telefono)", [
        ("valido", result.get("valid")),
        ("paese", result.get("country_code")),
        ("località", result.get("location")),
        ("operatore", result.get("carrier")),
        ("tipo linea", result.get("line_type")),
    ], result, rank=rank)


def _render_whatsmyname_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("WhatsMyName", result.get("error", "errore"), rank=rank)
    rows = "".join(
        f"<dt>{html.escape(f['name'])}</dt>"
        f'<dd><a href="{html.escape(f["url"])}" target="_blank" rel="noopener noreferrer">'
        f"{html.escape(f['url'])}</a></dd>"
        for f in result.get("found", [])
    )
    if not rows:
        rows = "<dt>risultato</dt><dd>nessun account trovato</dd>"
    raw_json = html.escape(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    rank_span = f'<span class="source-rank">#{rank}</span>' if rank else ""
    checked = result.get("checked", 0)
    total = result.get("total_sites", 0)
    return (
        '<div class="source-header">'
        f'<span class="source-name">{rank_span}WhatsMyName ({checked}/{total} siti)</span>'
        '<div class="source-meta"><span class="source-tag api">on-demand</span>'
        '<button type="button" class="btn-raw">raw</button></div>'
        '</div>'
        '<div class="source-body">'
        f'<dl class="kv-grid link-bundle-grid">{rows}</dl>'
        f'<pre class="source-raw-data">{raw_json}</pre>'
        '</div>'
    )


def _render_holehe_result(result: dict, rank: int = 0) -> str:
    if not result.get("ok"):
        return _render_lookup_error("Holehe", result.get("error", "errore"), rank=rank)
    rows = "".join(
        f"<dt>{html.escape(f['site'])}</dt><dd>{html.escape(f.get('domain') or '')}</dd>"
        for f in result.get("found", [])
    )
    if not rows:
        rows = "<dt>risultato</dt><dd>nessun account trovato</dd>"
    raw_json = html.escape(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    rank_span = f'<span class="source-rank">#{rank}</span>' if rank else ""
    checked = result.get("checked", 0)
    return (
        '<div class="source-header">'
        f'<span class="source-name">{rank_span}Holehe ({checked} servizi controllati)</span>'
        '<div class="source-meta"><span class="source-tag api">on-demand</span>'
        '<button type="button" class="btn-raw">raw</button></div>'
        '</div>'
        '<div class="source-body">'
        f'<dl class="kv-grid">{rows}</dl>'
        f'<pre class="source-raw-data">{raw_json}</pre>'
        '</div>'
    )


_LOOKUP_HANDLERS = {
    "site-crtsh": lambda v: crtsh_lookup(v),
    "site-nvd-nist": lambda v: nvd_lookup(v),
    "site-urlscan-domain": lambda v: urlscan_lookup(v, "domain"),
    "site-urlscan-url": lambda v: urlscan_lookup(v, "url"),
    "site-urlscan-ip": lambda v: urlscan_lookup(v, "ip"),
    "site-bgp-he-net": lambda v: cymru_asn_lookup(v),
    "site-abuseipdb": lambda v: abuseipdb_lookup(v),
    "site-virustotal-search": lambda v: virustotal_lookup(v),
    "site-shodan": lambda v: shodan_lookup(v),
    "site-gravatar": lambda v: gravatar_lookup(v),
    "site-xposedornot": lambda v: xposedornot_lookup(v),
    "site-phone-info": lambda v: phone_info_lookup(v),
    "site-threatfox": lambda v: threatfox_lookup(v),
    "site-urlhaus": lambda v: urlhaus_lookup(v),
    "site-otx": lambda v: otx_lookup(v),
    "site-hunter-verify": lambda v: hunter_verify_lookup(v),
    "site-cf": lambda v: codice_fiscale_lookup(v),
    "site-dorks-email": lambda v: dorks_lookup(v, "email"),
    "site-dorks-person": lambda v: dorks_lookup(v, "person_name"),
    "site-dorks-username": lambda v: dorks_lookup(v, "username"),
    "site-dorks-social": lambda v: dorks_lookup(v, "social_handle"),
    "site-dorks-phone": lambda v: dorks_lookup(v, "phone"),
    "site-dorks-domain": lambda v: dorks_lookup(v, "domain"),
    "site-dorks-ipv4": lambda v: dorks_lookup(v, "ipv4"),
    "site-emailrep": lambda v: emailrep_lookup(v),
    "site-hudsonrock-email": lambda v: hudsonrock_email_lookup(v),
    "site-hudsonrock-username": lambda v: hudsonrock_username_lookup(v),
    "site-github-api": lambda v: github_api_lookup(v),
    "site-keybase-api": lambda v: keybase_api_lookup(v),
    "site-gitlab-api": lambda v: gitlab_api_lookup(v),
    "site-reddit-api": lambda v: reddit_api_lookup(v),
    "site-ipqs-email": lambda v: ipqs_email_lookup(v),
    "site-ipqs-phone": lambda v: ipqs_phone_lookup(v),
    "site-numverify": lambda v: numverify_lookup(v),
    "site-whatsmyname": lambda v: whatsmyname_lookup(v),
    "site-holehe": lambda v: holehe_lookup(v),
}
_LOOKUP_RENDERERS = {
    "site-crtsh": _render_crtsh_result,
    "site-nvd-nist": _render_nvd_result,
    "site-urlscan-domain": _render_urlscan_result,
    "site-urlscan-url": _render_urlscan_result,
    "site-urlscan-ip": _render_urlscan_result,
    "site-bgp-he-net": _render_cymru_result,
    "site-abuseipdb": _render_abuseipdb_result,
    "site-virustotal-search": _render_virustotal_result,
    "site-shodan": _render_shodan_result,
    "site-gravatar": _render_gravatar_result,
    "site-xposedornot": _render_xposedornot_result,
    "site-phone-info": _render_phone_info_result,
    "site-threatfox": _render_threatfox_result,
    "site-urlhaus": _render_urlhaus_result,
    "site-otx": _render_otx_result,
    "site-hunter-verify": _render_hunter_result,
    "site-cf": _render_cf_result,
    "site-dorks-email": _render_dorks_result,
    "site-dorks-person": _render_dorks_result,
    "site-dorks-username": _render_dorks_result,
    "site-dorks-social": _render_dorks_result,
    "site-dorks-phone": _render_dorks_result,
    "site-dorks-domain": _render_dorks_result,
    "site-dorks-ipv4": _render_dorks_result,
    "site-emailrep": _render_emailrep_result,
    "site-hudsonrock-email": _render_hudsonrock_email_result,
    "site-hudsonrock-username": _render_hudsonrock_username_result,
    "site-github-api": _render_github_api_result,
    "site-keybase-api": _render_keybase_api_result,
    "site-gitlab-api": _render_gitlab_api_result,
    "site-reddit-api": _render_reddit_api_result,
    "site-ipqs-email": _render_ipqs_email_result,
    "site-ipqs-phone": _render_ipqs_phone_result,
    "site-numverify": _render_numverify_result,
    "site-whatsmyname": _render_whatsmyname_result,
    "site-holehe": _render_holehe_result,
}

# Risorse del catalogo che diventano lookup live invece di link esterno: sempre
# le keyless, più quelle key-gated il cui env var è configurato (vedi
# .env.example). Controllato a ogni richiesta (non in cache): impostare una
# key in .env e riavviare basta, non serve altro.
_KEYLESS_LIVE_RESOURCES = frozenset({
    "site-crtsh", "site-nvd-nist", "site-urlscan-domain", "site-urlscan-url", "site-bgp-he-net",
    # Shodan è keyless: InternetDB (gratuito, senza key) fa da fonte base;
    # SHODAN_API_KEY resta opzionale e aggiunge i dati host più ricchi.
    "site-shodan",
    # urlscan.io esteso agli IP; persone: Gravatar/XposedOrNot (email, keyless),
    # dati numero telefono (locale, offline via phonenumbers).
    "site-urlscan-ip", "site-gravatar", "site-xposedornot", "site-phone-info",
    # Codice Fiscale (reverse locale) + Google Dork per tipo (locale, solo URL).
    "site-cf",
    "site-dorks-email", "site-dorks-person", "site-dorks-username",
    "site-dorks-social", "site-dorks-phone", "site-dorks-domain", "site-dorks-ipv4",
    # Batch persone Wave A: reputation email, infostealer (email+username),
    # profili live (GitHub/Keybase/GitLab/Reddit). Tutte keyless.
    "site-emailrep", "site-hudsonrock-email", "site-hudsonrock-username",
    "site-github-api", "site-keybase-api", "site-gitlab-api", "site-reddit-api",
    # WhatsMyName/Holehe (Wave C1/C2): keyless ma ON-DEMAND — non partono da
    # sole (nessun data-auto-lookup nel template, vedi _macros.html). Essere
    # in questo set significa solo "non richiede API key", non "auto-fire".
    "site-whatsmyname", "site-holehe",
})
_KEY_GATED_RESOURCES = {
    "site-abuseipdb": "ABUSEIPDB_API_KEY",
    "site-virustotal-search": "VIRUSTOTAL_API_KEY",
    # Threat-intel a key gratuita (abuse.ch: una key per ThreatFox+URLhaus).
    "site-threatfox": "ABUSECH_API_KEY",
    "site-urlhaus": "ABUSECH_API_KEY",
    "site-otx": "OTX_API_KEY",
    "site-hunter-verify": "HUNTER_API_KEY",
    # Batch persone Wave B: breach/paste autorevoli, fraud score, validazione.
    "site-ipqs-email": "IPQS_API_KEY",
    "site-ipqs-phone": "IPQS_API_KEY",
    "site-numverify": "NUMVERIFY_API_KEY",
}


def _live_resource_ids() -> frozenset[str]:
    ids = set(_KEYLESS_LIVE_RESOURCES)
    for res_id, env_var in _KEY_GATED_RESOURCES.items():
        if os.environ.get(env_var):
            ids.add(res_id)
    return frozenset(ids)


def _render_label_area(observation_id: int, label: str | None) -> str:
    # Escape HTML su label perché viene da input utente (stored XSS).
    # Per l'attributo value uso quote=True che escape anche " e '.
    safe_display = html.escape(label) if label else f"Osservazione #{observation_id}"
    safe_value = html.escape(label or "", quote=True)
    return (
        f'<div class="obs-label-display" id="obs-label-display-{observation_id}">'
        f'<span class="obs-title-text">{safe_display}</span>'
        f'<button type="button" class="label-edit-trigger" '
        f'data-obs-id="{observation_id}" title="Rinomina">&#x270E;</button>'
        f"</div>"
        f'<form class="obs-label-form obs-label-form--hidden" '
        f'id="obs-label-form-{observation_id}" '
        f'hx-post="/e/{observation_id}/label" '
        f'hx-target="#obs-label-area-{observation_id}" hx-swap="innerHTML">'
        f'<input type="text" name="label" value="{safe_value}" '
        f'placeholder="Nome osservazione…" class="label-input">'
        f'<button type="submit" class="label-save-btn" title="Salva">&#x2713;</button>'
        f'<button type="button" class="label-cancel-btn" '
        f'data-obs-id="{observation_id}" title="Annulla">&#x2715;</button>'
        f"</form>"
    )
