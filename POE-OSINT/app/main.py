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

import html
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.middleware.base import BaseHTTPMiddleware

from app.scoring import build_markdown, compute_accuracy, compute_score, group_by_type
from app.extractors.regex_extractor import RegexExtractor
from app.extractors.spacy_extractor import SpacyExtractor
from app.recognizer import Recognizer
from app.storage import (
    DB_PATH,
    delete_observation,
    find_observations_with_entity,
    get_by_id,
    get_enrichment,
    get_recent,
    get_synthesis,
    init_db,
    remove_entity,
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

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 50_000


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            "font-src 'self' https://fonts.gstatic.com;"
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ollama = OllamaBackend(model="poe:latest")
    app.state.recognizer = Recognizer(RegexExtractor(), SpacyExtractor())
    app.state.llm_extractor = LLMExtractor(ollama)
    app.state.llm_backend = ollama
    app.state.enricher_registry = EnricherRegistry([IPEnricher(), WHOISEnricher()])
    logger.info("POE v0.5 starting — DB: %s", DB_PATH)
    yield


app = FastAPI(
    title="POE — Personal Observation Engine",
    description="v0.5: LLM synthesis + enrichers + entity cards espandibili.",
    version="0.5.0",
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


def _build_synthesis_prompt(raw_input: str, entities: list[dict]) -> tuple[str, str]:
    import yaml as _yaml
    from pathlib import Path as _Path
    p = _Path(__file__).parent / "llm" / "prompts" / "synthesis.yaml"
    tmpl = _yaml.safe_load(p.read_text(encoding="utf-8"))
    lines = [f"- [{e.get('type')}] {e.get('value')} ({e.get('confidence')})" for e in entities[:30]]
    user = tmpl["user"].replace("{raw_input}", raw_input[:500]).replace(
        "{entities}", "\n".join(lines) or "(nessuna entità)"
    )
    return user, tmpl["system"]


def _render_synthesis(text: str, model: str) -> str:
    return (
        f'<div class="synthesis-card" id="synthesis-panel">'
        f'<p class="synthesis-model">[{html.escape(model)}]</p>'
        f'<p class="synthesis-text">{html.escape(text)}</p>'
        f'</div>'
    )


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request, view: str = Query(default="all")):
    if view not in _VALID_VIEWS:
        view = "all"
    recent = _enrich_recent(get_recent(limit=10, filter_kept=view))
    return templates.TemplateResponse(
        request, "index.html", {"recent": recent, "current_view": view}
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
        # Sync deterministic extraction
        entities = request.app.state.recognizer.recognize(text)

        # Async LLM extraction (org_name, address) — no-op if Ollama offline
        llm_entities = await request.app.state.llm_extractor.async_extract(text)

        # Merge + dedup
        all_entities = list(set(entities) | set(llm_entities))

        # Social platform disambiguation (regex, zero cost)
        enriched = []
        for e in all_entities:
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

        observation_id = save_observation(text, all_entities)
        logger.info("analyze obs_id=%s entities=%d llm=%d", observation_id, len(all_entities), len(llm_entities))
    except Exception:
        logger.exception("recognize failed for input length=%d", len(text))
        return templates.TemplateResponse(
            request, "error.html", {"error": "Errore interno. Riprova."}, status_code=500
        )

    entity_dicts = [e.to_dict() for e in all_entities]
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
            "recent": _enrich_recent(get_recent(limit=10)),
            "current_view": "all",
        },
    )


@app.get("/e/{observation_id}", response_class=HTMLResponse)
def detail(request: Request, observation_id: int):
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    entity_dicts = obs["entities"]
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
    recent = _enrich_recent(get_recent(limit=10))
    oob = (
        '<section id="history" class="history" '
        'aria-labelledby="history-heading" hx-swap-oob="true">'
    )
    history_html = templates.get_template("_history.html").render(
        {"recent": recent, "current_view": "all"}
    )
    return HTMLResponse(oob + history_html + "</section>")


@app.get("/e/{observation_id}/export.md")
def export_markdown(observation_id: int):
    obs = get_by_id(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Osservazione non trovata")
    content = build_markdown(obs)
    return PlainTextResponse(
        content,
        headers={
            "Content-Disposition": f'attachment; filename="poe-{observation_id}.md"',
            "Content-Type": "text/plain; charset=utf-8",
        },
    )


@app.get("/e/cross/{entity_value:path}", response_class=HTMLResponse)
def cross_observation_route(request: Request, entity_value: str):
    if len(entity_value) > 500:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="entity_value too long")
    observations = find_observations_with_entity(entity_value)
    return templates.TemplateResponse(
        request,
        "cross_observation.html",
        {"entity_value": entity_value, "observations": observations, "count": len(observations)},
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
            '<section id="synthesis-panel"><div class="synthesis-card error">Ollama non raggiungibile (localhost:11434)</div></section>',
            status_code=503,
        )

    user_p, sys_p = _build_synthesis_prompt(obs.get("raw_input", ""), obs.get("entities", []))
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


@app.get("/health")
def health():
    ready = bool(getattr(app.state, "recognizer", None))
    return JSONResponse(
        {"status": "ok" if ready else "starting", "version": app.version},
        status_code=200 if ready else 503,
    )


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
