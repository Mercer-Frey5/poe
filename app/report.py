"""report.py — export ricco di un'osservazione: markdown investigativo + JSON completo.
Estende scoring.py (mantenuto scoped a score/accuracy/grouping): qui vive la
logica di presentazione del report (rischio, reputation, enrichment, correlazioni).

Stessa fonte di dati raw (enrichment metadata + risultati tool live già
interrogati) usata sia per il prompt LLM (vedi _build_entity_ai_prompt/
_build_synthesis_prompt in app/main.py) sia per il file scaricabile
dall'utente: un dato mancante nell'export era lo stesso motivo per cui il
LLM concludeva "dati insufficienti" nonostante l'informazione fosse già
disponibile in POE."""
from __future__ import annotations

import json as _json

from app.scoring import compute_accuracy, compute_score, group_by_type


def _entity_highlights(item: dict, risk: dict | None, pivot: dict | None) -> str:
    """Suffisso compatto con i segnali disponibili per un'entità. Vuoto se pulita."""
    parts: list[str] = []
    if risk and risk.get("level"):
        parts.append(f"[rischio: {risk['level']}]")
    meta = item.get("metadata") or {}
    reputation = meta.get("reputation") or {}
    if reputation.get("malicious"):
        sources = ", ".join(reputation.get("sources", [])) or "?"
        threat = reputation.get("threat")
        tag = f"⚠ malevolo ({sources}" + (f", {threat})" if threat else ")")
        parts.append(tag)
    if meta.get("country"):
        geo = meta["country"]
        if meta.get("city"):
            geo += f"/{meta['city']}"
        parts.append(f"geo: {geo}")
    if meta.get("registrar"):
        parts.append(f"registrar: {meta['registrar']}")
    if pivot and pivot.get("count", 0) >= 2:
        others = ", ".join(f"#{i}" for i in pivot.get("other_observation_ids", []))
        parts.append(f"visto in {pivot['count']} oss." + (f" ({others})" if others else ""))
    return " — " + "; ".join(parts) if parts else ""


def _entity_raw_block(item: dict, live_results: dict | None) -> list[str]:
    """Righe raw (JSON, indentate) allegate sotto un'entità: enrichment
    automatico COMPLETO (non solo i campi in _entity_highlights) + ogni
    risultato dei tool live già interrogati per quel valore, etichettato col
    nome della fonte. Vuoto se non c'è nulla oltre al valore."""
    lines: list[str] = []
    meta = item.get("metadata") or {}
    if meta:
        lines.append(f"  - enrichment: `{_json.dumps(meta, ensure_ascii=False, default=str)}`")
    for source_name, result in (live_results or {}).items():
        lines.append(f"  - {source_name}: `{_json.dumps(result, ensure_ascii=False, default=str)}`")
    return lines


def build_markdown_report(
    obs: dict,
    risk_by_value: dict | None = None,
    observation_risk: dict | None = None,
    pivot_info: dict | None = None,
    live_results_by_value: dict | None = None,
) -> str:
    """Export markdown investigativo: stesso formato base di sempre (header, input,
    entità, sintesi) + rischio/reputation/enrichment/correlazioni per ogni IOC, più
    il blocco raw (enrichment completo + tool live già interrogati, es. AbuseIPDB/
    VirusTotal/Shodan/BGP.HE.net/crt.sh) per ogni entità — stessi dati raw che vede
    il LLM in /entity-ai e /synthesis, così il file scaricato non è mai più povero
    di quello che POE sa davvero sull'osservazione."""
    risk_by_value = risk_by_value or {}
    pivot_info = pivot_info or {}
    live_results_by_value = live_results_by_value or {}

    obs_id = obs["id"]
    ts = obs.get("timestamp", "")
    label = obs.get("label") or f"Osservazione #{obs_id}"
    entities = obs.get("entities", [])
    score = compute_score(entities)
    accuracy = compute_accuracy(entities)
    kept_str = "kept" if obs.get("kept") else "draft"
    raw = obs.get("raw_input", "")

    lines = [
        f"# POE — {label}",
        "",
        f"Data: {ts}  ",
        f"Score: {score}  ",
        f"Accuratezza media: ~{accuracy}%  ",
        f"Stato: {kept_str}",
    ]

    if observation_risk and observation_risk.get("overall_level"):
        c = observation_risk["counts"]
        parts = []
        if c.get("critico"):
            parts.append(f"{c['critico']} critici")
        if c.get("sospetto"):
            parts.append(f"{c['sospetto']} sospetti")
        if c.get("basso"):
            parts.append(f"{c['basso']} bassi")
        lines.append(f"Rischio osservazione: ⚠ {' · '.join(parts)}  ")

    lines += [
        "",
        "## Input originale",
        "",
        "```",
        raw,
        "```",
        "",
        "## Entità estratte",
        "",
    ]

    for type_name, items in group_by_type(entities).items():
        lines.append(f"### {type_name} ({len(items)})")
        for item in items:
            conf = item.get("confidence", "medium")
            val = item["value"]
            orig = item.get("original", val)
            suffix = f" [{conf}]" if conf != "medium" else ""
            orig_note = f" ← {orig}" if orig != val else ""
            highlights = _entity_highlights(item, risk_by_value.get(val), pivot_info.get(val))
            lines.append(f"- {val}{orig_note}{suffix}{highlights}")
            lines.extend(_entity_raw_block(item, live_results_by_value.get(val)))
        lines.append("")

    correlated = [(val, info) for val, info in pivot_info.items() if info.get("count", 0) >= 2]
    if correlated:
        lines.append("## Correlazioni")
        lines.append("")
        for val, info in correlated:
            others = ", ".join(f"#{i}" for i in info.get("other_observation_ids", []))
            lines.append(f"- **{val}** — visto in {info['count']} osservazioni ({others})")
        lines.append("")

    synthesis_text = obs.get("synthesis_text")
    synthesis_model = obs.get("synthesis_model") or "unknown"
    if synthesis_text:
        lines.append("## Sintesi Intelligence")
        lines.append(f"_Generata da {synthesis_model}_")
        lines.append("")
        lines.append(synthesis_text)
        lines.append("")

    return "\n".join(lines)


def build_json_report(
    obs: dict,
    risk_by_value: dict | None = None,
    observation_risk: dict | None = None,
    pivot_info: dict | None = None,
    live_results_by_value: dict | None = None,
) -> dict:
    """Export JSON completo: tutto ciò che POE sa su questa osservazione, inclusi
    i risultati dei tool live già interrogati (stessi dati grezzi passati al LLM)."""
    risk_by_value = risk_by_value or {}
    pivot_info = pivot_info or {}
    live_results_by_value = live_results_by_value or {}
    entities = obs.get("entities", [])

    synthesis_text = obs.get("synthesis_text")
    synthesis = (
        {"text": synthesis_text, "model": obs.get("synthesis_model")}
        if synthesis_text else None
    )

    return {
        "id": obs["id"],
        "timestamp": obs.get("timestamp"),
        "label": obs.get("label"),
        "kept": bool(obs.get("kept", False)),
        "raw_input": obs.get("raw_input", ""),
        "score": compute_score(entities),
        "accuracy": compute_accuracy(entities),
        "risk": observation_risk or {"counts": {"critico": 0, "sospetto": 0, "basso": 0}, "overall_level": None},
        "synthesis": synthesis,
        "entities": [
            {
                "type": e["type"],
                "value": e["value"],
                "original": e.get("original", e["value"]),
                "confidence": e.get("confidence", "medium"),
                "metadata": e.get("metadata") or {},
                "risk": risk_by_value.get(e["value"], {"score": 0, "level": None, "factors": []}),
                "pivot": pivot_info.get(e["value"], {"count": 0, "other_observation_ids": []}),
                "live_results": live_results_by_value.get(e["value"], {}),
            }
            for e in entities
        ],
    }
