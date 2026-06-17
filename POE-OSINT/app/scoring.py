"""Domain helpers: score, accuracy, grouping, markdown rendering."""
from __future__ import annotations

_TYPE_DISPLAY_ORDER = [
    "url", "email", "domain", "ipv4",
    "hash_md5", "hash_sha256", "cve",
    "phone", "tax_id", "vat_id",
    "social_handle", "username", "birth_date", "person_name",
]

_SCORE_WEIGHTS: dict[str, int] = {"high": 3, "medium": 2, "low": 1}
_ACCURACY_WEIGHTS: dict[str, int] = {"high": 90, "medium": 65, "low": 35}


def group_by_type(entities: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for e in entities:
        meta = e.get("metadata") or {}
        groups.setdefault(e["type"], []).append({
            "value": e["value"],
            "original": e.get("original", e["value"]),
            "confidence": e.get("confidence", "medium"),
            "metadata": meta,
        })
    ordered: dict[str, list[dict]] = {}
    for t in _TYPE_DISPLAY_ORDER:
        if t in groups:
            ordered[t] = sorted(groups[t], key=lambda x: x["value"].lower())
    for t in sorted(groups.keys()):
        if t not in ordered:
            ordered[t] = sorted(groups[t], key=lambda x: x["value"].lower())
    return ordered


def compute_score(entities: list[dict]) -> int:
    base = sum(_SCORE_WEIGHTS.get(e.get("confidence", "medium"), 2) for e in entities)
    variety = len({e["type"] for e in entities}) * 2
    return base + variety


def compute_accuracy(entities: list[dict]) -> int:
    if not entities:
        return 0
    total = sum(_ACCURACY_WEIGHTS.get(e.get("confidence", "medium"), 65) for e in entities)
    return round(total / len(entities))


def build_markdown(obs: dict) -> str:
    obs_id = obs["id"]
    ts = obs.get("timestamp", "")
    label = obs.get("label") or f"Osservazione #{obs_id}"
    score = compute_score(obs.get("entities", []))
    accuracy = compute_accuracy(obs.get("entities", []))
    kept_str = "kept" if obs.get("kept") else "draft"
    raw = obs.get("raw_input", "")

    lines = [
        f"# POE — {label}",
        "",
        f"Data: {ts}  ",
        f"Score: {score}  ",
        f"Accuratezza media: ~{accuracy}%  ",
        f"Stato: {kept_str}",
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

    for type_name, items in group_by_type(obs.get("entities", [])).items():
        lines.append(f"### {type_name} ({len(items)})")
        for item in items:
            conf = item.get("confidence", "medium")
            val = item["value"]
            orig = item.get("original", val)
            suffix = f" [{conf}]" if conf != "medium" else ""
            orig_note = f" ← {orig}" if orig != val else ""
            lines.append(f"- {val}{orig_note}{suffix}")
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
