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


